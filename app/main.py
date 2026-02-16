from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from core.bootstrap import bootstrap_repo
from core.graph import build_graph, graph_as_json, render_graph_text
from core.health import compute_and_write_health, compute_health_for_system
from core.registry import load_registry, load_registry_systems, registry_path, upsert_system
from core.reporting import compute_report, format_text, load_history
from core.storage import append_event, create_contract
from core.validate import validate_repo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrapping-engine",
        description="Bootstrapping Engine v0.1 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create required folders and primitive baseline files if missing.")

    health_cmd = subparsers.add_parser("health", help="Compute health and write latest + history snapshots.")
    health_cmd.add_argument("--all", action="store_true", help="Compute per-system health from registry globs.")
    health_cmd.add_argument("--registry", default=None, help="Optional path to systems registry JSON.")
    health_cmd.add_argument("--json", action="store_true", help="Print --all output as JSON.")
    health_cmd.add_argument("--strict", action="store_true", help="Exit non-zero if policy-blocking systems are red (with --all).")
    health_cmd.add_argument("--include-staging", action="store_true", help="Strict includes staging tier.")
    health_cmd.add_argument("--include-dev", action="store_true", help="Strict includes dev tier (implies staging).")

    contract = subparsers.add_parser("contract", help="Contract commands.")
    contract_sub = contract.add_subparsers(dest="contract_command", required=True)
    contract_new = contract_sub.add_parser("new", help='Create a new contract: contract new <system_id> "<name>"')
    contract_new.add_argument("system_id", help="System identifier for the contract.")
    contract_new.add_argument("name", help="Contract name.")

    log_cmd = subparsers.add_parser("log", help="Append an event record.")
    log_cmd.add_argument("system_id", help="System identifier for the event.")
    log_cmd.add_argument("event_type", help="Event type.")

    system_cmd = subparsers.add_parser("system", help="System registry commands.")
    system_sub = system_cmd.add_subparsers(dest="system_command", required=True)
    system_add = system_sub.add_parser("add", help='Register a system: system add <system_id> "<name>"')
    system_add.add_argument("system_id", help="System identifier.")
    system_add.add_argument("name", help="System display name used for initial contract creation.")
    system_sub.add_parser("list", help="List systems with health rollup.")

    report_cmd = subparsers.add_parser("report", help="Meta-report commands.")
    report_sub = report_cmd.add_subparsers(dest="report_command", required=True)
    report_health = report_sub.add_parser("health", help="Generate health report from snapshot history.")
    report_health.add_argument("--days", type=int, default=30, help="Analyze snapshots within last N days.")
    report_health.add_argument("--tail", type=int, default=2000, help="Max history lines read from JSONL.")
    report_health.add_argument("--json", action="store_true", help="Print report as JSON.")
    report_health.add_argument("--strict", action="store_true", help="Exit non-zero if strict readiness fails now.")
    report_health.add_argument("--include-staging", action="store_true", help="Strict policy includes staging tier.")
    report_health.add_argument("--include-dev", action="store_true", help="Strict policy includes dev tier (implies staging).")
    report_health.add_argument("--no-hints", action="store_true", help="Disable action hints in report output.")
    report_health.add_argument("--registry", default=None, help="Optional path to systems registry JSON.")

    report_graph = report_sub.add_parser("graph", help="Print dependency graph (text or JSON).")
    report_graph.add_argument("--json", action="store_true", help="Emit JSON.")
    report_graph.add_argument("--registry-path", default=None, help="Override registry path.")

    subparsers.add_parser("validate", help="Validate registry, schema, globs, and event timestamps.")

    subparsers.add_parser("run", help="One-command run: init then health.")
    return parser


def _emit_health_snapshot() -> None:
    payload, snapshot_files = compute_and_write_health()
    print(
        json.dumps(
            {
                "status": payload["status"],
                "score_total": payload["score_total"],
                "violations": payload["violations"],
                "violations_display": ",".join(payload["violations"]) if payload["violations"] else "none",
                "global_includes_samples": False,
                "snapshot_files": snapshot_files,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _health_payloads(registry_path: str | None) -> list[dict]:
    out: list[dict] = []
    for spec in load_registry(registry_path):
        payload = compute_health_for_system(spec.system_id, spec.contracts_glob, spec.events_glob)
        payload = {"system_id": spec.system_id, **payload}
        out.append(payload)
    return out


def _health_rows(registry_path: str | None) -> list[tuple[str, str, float, str, bool]]:
    rows: list[tuple[str, str, float, str, bool]] = []
    for spec in load_registry(registry_path):
        payload = compute_health_for_system(spec.system_id, spec.contracts_glob, spec.events_glob)
        violations = ",".join(payload["violations"]) if payload["violations"] else "none"
        rows.append((spec.system_id, payload["status"], float(payload["score_total"]), violations, spec.is_sample))
    return rows


def _blocked_tiers(include_staging: bool, include_dev: bool) -> set[str]:
    tiers = {"prod"}
    if include_staging or include_dev:
        tiers.add("staging")
    if include_dev:
        tiers.add("dev")
    return tiers


def _has_policy_red(registry_path: str | None, blocked_tiers: set[str]) -> bool:
    for spec in load_registry(registry_path):
        if spec.is_sample:
            continue
        if spec.tier not in blocked_tiers:
            continue

        payload = compute_health_for_system(
            system_id=spec.system_id,
            contracts_glob=spec.contracts_glob,
            events_glob=spec.events_glob,
        )
        if payload.get("status") == "red":
            return True
    return False


def _emit_health_all(registry_path: str | None, as_json: bool) -> None:
    payloads = _health_payloads(registry_path)
    if as_json:
        systems = [
            {
                "system_id": p["system_id"],
                "status": p["status"],
                "score_total": p["score_total"],
                "violations": p["violations"],
                "counts": p["counts"],
                "scores": p["scores"],
                "per_system": p.get("per_system", []),
            }
            for p in payloads
        ]
        print(json.dumps({"systems": systems}, indent=2, sort_keys=True))
        return

    print("system_id | status | score_total | violations | sample")
    print("-" * 80)
    for system_id, status, score_total, violations, is_sample in _health_rows(registry_path):
        sample = "yes" if is_sample else "no"
        print(f"{system_id} | {status} | {score_total:.2f} | {violations} | {sample}")


def _emit_report_health(days: int, tail: int, as_json: bool, strict: bool, registry_path: str | None, include_hints: bool, include_staging: bool, include_dev: bool) -> int:
    history_path = Path("data/snapshots/health_history.jsonl")
    if not history_path.exists() or not load_history(tail=1):
        print("No health history found at data/snapshots/health_history.jsonl")
        return 0

    blocked = sorted(_blocked_tiers(include_staging, include_dev))
    strict_policy = {
        "strict_blocked_tiers": blocked,
        "include_staging": bool(include_staging),
        "include_dev": bool(include_dev),
    }
    report = compute_report(
        days=days,
        tail=tail,
        strict=strict,
        registry_path=registry_path,
        include_hints=include_hints,
        strict_policy=strict_policy,
    )
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report, days=days))

    if strict and not report["summary"]["strict_ready_now"]:
        return 2
    return 0


def _emit_report_graph(as_json: bool, registry_path_arg: str | None) -> int:
    reg_path = registry_path(registry_path_arg)
    registry_obj = json.loads(reg_path.read_text(encoding="utf-8"))
    systems = load_registry_systems(registry_obj)

    g = build_graph(systems)

    if as_json:
        print(json.dumps(graph_as_json(g), indent=2, sort_keys=True))
    else:
        print(render_graph_text(g))

    return 0


def _system_add(system_id: str, name: str) -> None:
    contracts_glob = f"data/contracts/{system_id}-*.json"
    events_glob = f"data/logs/{system_id}-events.jsonl"

    changed = upsert_system(system_id, contracts_glob, events_glob)

    if not any(Path().glob(contracts_glob)):
        create_contract(system_id=system_id, name=name)

    if changed:
        append_event(system_id=system_id, event_type="registered")
        print(json.dumps({"system_id": system_id, "message": "registered"}, indent=2, sort_keys=True))
    else:
        print(json.dumps({"system_id": system_id, "message": "already exists"}, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 2:
            return 1
        raise

    if args.command == "init":
        created = bootstrap_repo()
        print(json.dumps({"created": [str(p) for p in created]}, indent=2, sort_keys=True))
        _emit_health_snapshot()
        return 0

    if args.command == "health":
        if args.all:
            _emit_health_all(args.registry, args.json)
            blocked = _blocked_tiers(args.include_staging, args.include_dev)
            if args.strict and _has_policy_red(args.registry, blocked):
                return 2
        else:
            _emit_health_snapshot()
        return 0

    if args.command == "contract":
        if args.contract_command == "new":
            bootstrap_repo()
            path = create_contract(system_id=args.system_id, name=args.name)
            print(json.dumps({"contract_path": str(path)}, indent=2, sort_keys=True))
            _emit_health_snapshot()
            return 0
        parser.error("Unknown contract command.")

    if args.command == "log":
        bootstrap_repo()
        event = append_event(system_id=args.system_id, event_type=args.event_type)
        print(json.dumps({"event": event}, indent=2, sort_keys=True))
        _emit_health_snapshot()
        return 0

    if args.command == "system":
        bootstrap_repo()
        if args.system_command == "add":
            _system_add(args.system_id, args.name)
            return 0
        if args.system_command == "list":
            _emit_health_all(None, as_json=False)
            return 0
        parser.error("Unknown system command.")

    if args.command == "report":
        bootstrap_repo()
        if args.report_command == "health":
            return _emit_report_health(
                args.days,
                args.tail,
                args.json,
                args.strict,
                args.registry,
                include_hints=not args.no_hints,
                include_staging=args.include_staging,
                include_dev=args.include_dev,
            )
        if args.report_command == "graph":
            return _emit_report_graph(args.json, args.registry_path)
        parser.error("Unknown report command.")


    if args.command == "validate":
        bootstrap_repo()
        errors = validate_repo()
        if errors:
            for err in errors:
                print(err)
            return 1
        print("VALIDATE_OK")
        return 0

    if args.command == "run":
        created = bootstrap_repo()
        print(json.dumps({"created": [str(p) for p in created]}, indent=2, sort_keys=True))
        _emit_health_snapshot()
        return 0

    try:
        parser.error("Unknown command.")
    except SystemExit as exc:
        if exc.code == 2:
            return 1
        raise
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
