from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from core.bootstrap import bootstrap_repo
from core.export import export_bundle
from core.graph import build_graph, graph_as_json, render_graph_text
from core.health import compute_and_write_health, compute_health_for_system
from core.registry import load_registry, load_registry_systems, registry_path, upsert_system
from core.snapshot import build_snapshot_ledger_entry, compute_stats, run_snapshot_loop, tail_snapshots, write_snapshot_ledger
from core.reporting import compute_report, format_text, load_history
from core.strict import build_policy, collect_strict_failures, strict_failure_payload
from core.storage import append_event, create_contract
from core.timeutil import parse_iso_utc
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
    health_cmd.add_argument(
        "--enforce-sla",
        action="store_true",
        help="In strict mode, also fail gate when SLA is breached for policy tiers (advisory becomes enforceable).",
    )
    health_cmd.add_argument(
        "--as-of",
        default=None,
        help="Replay mode timestamp in ISO8601 (e.g., 2026-02-16T12:00:00Z).",
    )
    health_cmd.add_argument(
        "--hide-samples",
        action="store_true",
        help="Hide sample systems from --all output (table + JSON).",
    )

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
    report_health.add_argument(
        "--enforce-sla",
        action="store_true",
        help="In strict mode, also fail gate when SLA is breached for policy tiers (advisory becomes enforceable).",
    )
    report_health.add_argument(
        "--as-of",
        default=None,
        help="Replay mode timestamp in ISO8601 (e.g., 2026-02-16T12:00:00Z).",
    )
    report_health.add_argument("--no-hints", action="store_true", help="Disable action hints in report output.")
    report_health.add_argument("--registry", default=None, help="Optional path to systems registry JSON.")

    
    report_snapshot = report_sub.add_parser("snapshot", help="Build/write append-only report snapshot ledger entry.")
    report_snapshot.add_argument("--days", type=int, default=30, help="Analyze snapshots within last N days.")
    report_snapshot.add_argument("--tail", type=int, default=2000, help="Max history lines read from JSONL.")
    report_snapshot.add_argument("--strict", action="store_true", help="Compute strict readiness in the report payload.")
    report_snapshot.add_argument("--include-staging", action="store_true", help="Strict policy includes staging tier.")
    report_snapshot.add_argument("--include-dev", action="store_true", help="Strict policy includes dev tier (implies staging).")
    report_snapshot.add_argument("--no-hints", action="store_true", help="Disable action hints in report payload.")
    report_snapshot.add_argument("--registry", default=None, help="Optional path to systems registry JSON.")
    report_snapshot.add_argument("--write", action="store_true", help="Append snapshot to data/snapshots/report_snapshot_history.jsonl.")
    report_snapshot.add_argument("--json", action="store_true", help="Print snapshot payload as JSON.")
    report_snapshot.add_argument(
        "--enforce-sla",
        action="store_true",
        help="In strict mode, also fail gate when SLA is breached for policy tiers (advisory becomes enforceable).",
    )
    report_snapshot.add_argument(
        "--as-of",
        default=None,
        help="Replay mode timestamp in ISO8601 (e.g., 2026-02-16T12:00:00Z).",
    )

    # v2.1 Full-A: snapshot subcommands (read-only + loop)
    report_snapshot_sub = report_snapshot.add_subparsers(dest="snapshot_command", required=False)

    snap_tail = report_snapshot_sub.add_parser("tail", help="Tail report snapshot ledger.")
    snap_tail.add_argument("--ledger", default="data/snapshots/report_snapshot_history.jsonl", help="Ledger path (jsonl).")
    snap_tail.add_argument("--n", type=int, default=50, help="Number of entries.")
    snap_tail.add_argument("--since-hours", type=int, default=None, help="Filter to last N hours.")
    snap_tail.add_argument("--json", action="store_true", help="Emit JSON list.")
    snap_tail.add_argument("--pretty", action="store_true", help="Emit human-readable summary.")

    snap_stats = report_snapshot_sub.add_parser("stats", help="Compute snapshot ledger stats.")
    snap_stats.add_argument("--ledger", default="data/snapshots/report_snapshot_history.jsonl", help="Ledger path (jsonl).")
    snap_stats.add_argument("--days", type=int, default=7, help="Window size in days.")
    snap_stats.add_argument("--json", action="store_true", help="Emit JSON payload.")

    snap_run = report_snapshot_sub.add_parser("run", help="Write snapshots on a timer loop.")
    snap_run.add_argument("--every", type=int, default=60, help="Seconds between writes.")
    snap_run.add_argument("--count", type=int, default=60, help="How many snapshots to write.")
    snap_run.add_argument("--json", action="store_true", help="Emit JSON payload.")


    report_graph = report_sub.add_parser("graph", help="Print dependency graph (text or JSON).")
    report_graph.add_argument("--json", action="store_true", help="Emit JSON.")
    report_graph.add_argument("--registry", "--registry-path", default=None, help="Optional path to systems registry JSON.")

    report_export = report_sub.add_parser("export", help="Write a deterministic export bundle to a directory.")
    report_export.add_argument("--out", required=True, help="Output directory for bundle.")
    report_export.add_argument("--days", type=int, default=30, help="Analyze snapshots within last N days.")
    report_export.add_argument("--tail", type=int, default=2000, help="Max history lines read from JSONL.")
    report_export.add_argument("--registry", default=None, help="Optional path to systems registry JSON.")
    report_export.add_argument("--strict", action="store_true", help="Include strict readiness + strict_failure in health export.")
    report_export.add_argument("--include-staging", action="store_true", help="Strict policy includes staging tier.")
    report_export.add_argument("--include-dev", action="store_true", help="Strict policy includes dev tier (implies staging).")
    report_export.add_argument("--enforce-sla", action="store_true", help="When used with --strict, include SLA policy breaches.")
    report_export.add_argument("--no-hints", action="store_true", help="Disable action hints in report output.")
    report_export.add_argument("--ledger", default="data/snapshots/report_snapshot_history.jsonl", help="Path to snapshot ledger JSONL.")
    report_export.add_argument("--n-tail", type=int, default=50, help="How many ledger lines to include in tail export.")

    subparsers.add_parser("validate", help="Validate registry, schema, globs, and event timestamps.")

    failcase_cmd = subparsers.add_parser("failcase", help="Generate deterministic failcase fixtures.")
    failcase_sub = failcase_cmd.add_subparsers(dest="failcase_command", required=True)
    failcase_create = failcase_sub.add_parser("create", help="Create failcase fixture directory.")
    failcase_create.add_argument("--path", required=True, help="Target directory for failcase fixture.")
    failcase_create.add_argument(
        "--mode",
        choices=["sla-breach"],
        default="sla-breach",
        help="Failcase scenario mode.",
    )

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


def _health_payloads(
    registry_path: str | None,
    hide_samples: bool,
    *,
    as_of: datetime | None = None,
) -> list[dict]:
    out: list[dict] = []
    for spec in load_registry(registry_path):
        if hide_samples and spec.is_sample:
            continue
        payload = compute_health_for_system(
            spec.system_id,
            spec.contracts_glob,
            spec.events_glob,
            registry_path=registry_path,
            as_of=as_of,
        )
        payload = {"system_id": spec.system_id, **payload}
        out.append(payload)
    return out


def _health_rows(
    registry_path: str | None,
    hide_samples: bool,
    *,
    as_of: datetime | None = None,
) -> list[tuple[str, str, float, str, bool]]:
    rows: list[tuple[str, str, float, str, bool]] = []
    for spec in load_registry(registry_path):
        if hide_samples and spec.is_sample:
            continue
        payload = compute_health_for_system(
            spec.system_id,
            spec.contracts_glob,
            spec.events_glob,
            registry_path=registry_path,
            as_of=as_of,
        )
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


def _parse_as_of(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = parse_iso_utc(value)
    if dt is None:
        raise ValueError(f"Invalid --as-of timestamp: {value}")
    return dt


def _collect_strict_failures(
    registry_path_arg: str | None,
    blocked_tiers: set[str],
    enforce_sla: bool,
    *,
    as_of: datetime | None = None,
) -> list[dict]:
    include_staging = "staging" in blocked_tiers or "dev" in blocked_tiers
    include_dev = "dev" in blocked_tiers
    policy = build_policy(include_staging=include_staging, include_dev=include_dev, enforce_sla=bool(enforce_sla))
    return collect_strict_failures(registry_path_arg, policy, as_of=as_of)


def _emit_strict_failure_json(
    blocked_tiers: set[str],
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    reasons: list[dict],
) -> None:
    """
    Emit a single JSON line to stderr so stdout JSON remains clean.
    """
    payload = _build_strict_failure_payload(
        blocked_tiers=blocked_tiers,
        include_staging=include_staging,
        include_dev=include_dev,
        enforce_sla=enforce_sla,
        reasons=reasons,
    )
    print(json.dumps(payload, sort_keys=True), file=sys.stderr)


def _build_strict_failure_payload(
    blocked_tiers: set[str],
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    reasons: list[dict],
) -> dict:
    policy = build_policy(include_staging=bool(include_staging), include_dev=bool(include_dev), enforce_sla=bool(enforce_sla))
    return strict_failure_payload(policy, reasons)


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
            registry_path=registry_path,
        )
        if payload.get("status") == "red":
            return True
    return False


def _emit_health_all(
    registry_path: str | None,
    as_json: bool,
    hide_samples: bool = False,
    *,
    as_of: datetime | None = None,
) -> None:
    payloads = _health_payloads(registry_path, hide_samples=hide_samples, as_of=as_of)
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
        payload: dict[str, object] = {"systems": systems}
        if as_of is not None:
            payload["as_of"] = as_of.astimezone(UTC).isoformat().replace("+00:00", "Z")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print("system_id | status | score_total | violations | sample")
    print("-" * 80)
    for system_id, status, score_total, violations, is_sample in _health_rows(
        registry_path,
        hide_samples=hide_samples,
        as_of=as_of,
    ):
        sample = "yes" if is_sample else "no"
        print(f"{system_id} | {status} | {score_total:.2f} | {violations} | {sample}")


def _emit_report_health(
    days: int,
    tail: int,
    as_json: bool,
    strict: bool,
    registry_path: str | None,
    as_of: datetime | None,
    include_hints: bool,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
) -> int:
    history_path = Path("data/snapshots/health_history.jsonl")
    if not history_path.exists() or not load_history(tail=1):
        print("No health history found at data/snapshots/health_history.jsonl")
        return 0

    blocked_tiers = _blocked_tiers(include_staging, include_dev)
    blocked = sorted(blocked_tiers)
    strict_policy = {
        "strict_blocked_tiers": blocked,
        "include_staging": bool(include_staging),
        "include_dev": bool(include_dev),
        "enforce_sla": bool(enforce_sla),
    }
    report = compute_report(
        days=days,
        tail=tail,
        strict=strict,
        registry_path=registry_path,
        include_hints=include_hints,
        strict_policy=strict_policy,
        as_of=as_of,
    )

    reasons: list[dict] = []
    strict_failure_payload: dict | None = None
    if strict:
        reasons = _collect_strict_failures(
            registry_path,
            blocked_tiers,
            enforce_sla=bool(enforce_sla),
            as_of=as_of,
        )
        if reasons:
            strict_failure_payload = _build_strict_failure_payload(
                blocked_tiers=blocked_tiers,
                include_staging=bool(include_staging),
                include_dev=bool(include_dev),
                enforce_sla=bool(enforce_sla),
                reasons=reasons,
            )
        if as_json:
            report = {**report, "strict_failure": strict_failure_payload}

    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report, days=days))

    if strict and reasons:
        if strict_failure_payload is None:
            _emit_strict_failure_json(
                blocked_tiers=blocked_tiers,
                include_staging=bool(include_staging),
                include_dev=bool(include_dev),
                enforce_sla=bool(enforce_sla),
                reasons=reasons,
            )
        else:
            print(json.dumps(strict_failure_payload, sort_keys=True), file=sys.stderr)
        return 2
    return 0


def _emit_report_snapshot(
    days: int,
    tail: int,
    strict: bool,
    registry_path_arg: str | None,
    as_of: datetime | None,
    include_hints: bool,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    write: bool,
    as_json: bool,
) -> int:
    blocked_tiers = _blocked_tiers(include_staging, include_dev)
    blocked = sorted(blocked_tiers)
    strict_policy = {
        "strict_blocked_tiers": blocked,
        "include_staging": bool(include_staging),
        "include_dev": bool(include_dev),
        "enforce_sla": bool(enforce_sla),
    }
    report = compute_report(
        days=days,
        tail=tail,
        strict=strict,
        registry_path=registry_path_arg,
        include_hints=include_hints,
        strict_policy=strict_policy,
        as_of=as_of,
    )
    report["strict_failure"] = None
    if strict:
        reasons = _collect_strict_failures(
            registry_path_arg,
            blocked_tiers,
            enforce_sla=bool(enforce_sla),
            as_of=as_of,
        )
        if reasons:
            report["strict_failure"] = _build_strict_failure_payload(
                blocked_tiers=blocked_tiers,
                include_staging=bool(include_staging),
                include_dev=bool(include_dev),
                enforce_sla=bool(enforce_sla),
                reasons=reasons,
            )

    entry = build_snapshot_ledger_entry(report)
    path = None
    if write:
        path = write_snapshot_ledger(report)

    payload = {
        "written": bool(write),
        "path": str(path) if path is not None else None,
        "as_of": _iso_utc(as_of) if as_of is not None else None,
        "snapshot": entry,
    }

    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "written": payload["written"],
                    "path": payload["path"],
                    "ts": entry.get("ts"),
                    "systems": len(entry.get("systems", [])),
                },
                indent=2,
                sort_keys=True,
            )
        )
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


def _emit_report_export(
    out_dir: str,
    days: int,
    tail: int,
    registry_path_arg: str | None,
    strict: bool,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
    include_hints: bool,
    ledger_path: str,
    n_tail: int,
) -> int:
    written = export_bundle(
        out_dir=out_dir,
        days=days,
        tail=tail,
        registry_path=registry_path_arg,
        strict=bool(strict),
        include_staging=bool(include_staging),
        include_dev=bool(include_dev),
        enforce_sla=bool(enforce_sla),
        include_hints=bool(include_hints),
        ledger_path=ledger_path,
        n_tail=int(n_tail),
    )
    print(json.dumps({"written": [str(p) for p in written]}, indent=2, sort_keys=True))
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


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl_file(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def _create_failcase_sla_breach(target_dir: Path) -> Path:
    now_utc = datetime.now(timezone.utc)
    stale_ts = _iso_utc(now_utc - timedelta(days=30))

    contracts_path = target_dir / "data" / "contracts" / "prod-fail-0001.json"
    logs_path = target_dir / "data" / "logs" / "prod-fail-events.jsonl"
    registry_path_out = target_dir / "data" / "registry" / "systems.json"

    _write_json_file(
        contracts_path,
        {
            "contract_id": "prod-fail-0001",
            "system_id": "prod-fail",
            "name": "Prod failcase contract",
            "primitives_used": ["a", "b", "c"],
            "invariants": ["a", "b", "c"],
        },
    )
    _write_jsonl_file(
        logs_path,
        [
            {
                "event_id": f"prod-fail-evt-{i:06d}",
                "system_id": "prod-fail",
                "event_type": "status_update",
                "ts": stale_ts,
            }
            for i in range(1, 9)
        ],
    )
    _write_json_file(
        registry_path_out,
        {
            "systems": [
                {
                    "system_id": "prod-fail",
                    "contracts_glob": "data/contracts/prod-fail-*.json",
                    "events_glob": "data/logs/prod-fail-events.jsonl",
                    "is_sample": False,
                    "tier": "prod",
                }
            ]
        },
    )
    return registry_path_out


def _emit_failcase_create(mode: str, path_arg: str) -> int:
    target_dir = Path(path_arg).expanduser()
    if not target_dir.is_absolute():
        target_dir = Path.cwd() / target_dir
    if mode == "sla-breach":
        reg = _create_failcase_sla_breach(target_dir)
        print(
            json.dumps(
                {
                    "created": True,
                    "mode": mode,
                    "path": str(target_dir),
                    "registry": str(reg),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    raise ValueError(f"Unsupported failcase mode: {mode}")


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
        try:
            as_of = _parse_as_of(getattr(args, "as_of", None))
        except ValueError as exc:
            print(str(exc))
            return 1
        if args.all:
            _emit_health_all(args.registry, args.json, hide_samples=bool(args.hide_samples), as_of=as_of)
            blocked = _blocked_tiers(args.include_staging, args.include_dev)
            if args.strict:
                reasons = _collect_strict_failures(
                    args.registry,
                    blocked,
                    enforce_sla=bool(args.enforce_sla),
                    as_of=as_of,
                )
                if reasons:
                    _emit_strict_failure_json(
                        blocked_tiers=blocked,
                        include_staging=bool(args.include_staging),
                        include_dev=bool(args.include_dev),
                        enforce_sla=bool(args.enforce_sla),
                        reasons=reasons,
                    )
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
            try:
                as_of = _parse_as_of(getattr(args, "as_of", None))
            except ValueError as exc:
                print(str(exc))
                return 1
            return _emit_report_health(
                args.days,
                args.tail,
                args.json,
                args.strict,
                args.registry,
                as_of=as_of,
                include_hints=not args.no_hints,
                include_staging=args.include_staging,
                include_dev=args.include_dev,
                enforce_sla=args.enforce_sla,
            )
        if args.report_command == "graph":
            return _emit_report_graph(args.json, args.registry)
        if args.report_command == "snapshot":
            # Subcommand mode: tail/stats/run (Full-A)
            if getattr(args, "snapshot_command", None) == "tail":
                rows = tail_snapshots(args.ledger, n=args.n, since_hours=args.since_hours)
                if args.json:
                    print(json.dumps(rows, indent=2, sort_keys=True))
                else:
                    # pretty summary
                    for r in rows:
                        ts = str(r.get("ts", ""))
                        summary = r.get("summary", {})
                        strict_now = bool(summary.get("strict_ready_now", False)) if isinstance(summary, dict) else False
                        status = str(summary.get("status", "unknown")) if isinstance(summary, dict) else "unknown"
                        print(f"{ts} | status={status} | strict_ready_now={strict_now}")
                return 0

            if getattr(args, "snapshot_command", None) == "stats":
                payload = compute_stats(args.ledger, days=int(args.days))
                if args.json:
                    print(json.dumps(payload, indent=2, sort_keys=True))
                else:
                    print(json.dumps(payload, indent=2, sort_keys=True))
                return 0

            if getattr(args, "snapshot_command", None) == "run":
                # uses existing report snapshot compute + write path
                def _write_once() -> None:
                    _emit_report_snapshot(
                        days=30,
                        tail=2000,
                        strict=True,
                        registry_path_arg=None,
                        as_of=None,
                        include_hints=True,
                        include_staging=False,
                        include_dev=False,
                        enforce_sla=False,
                        write=True,
                        as_json=True,
                    )

                res = run_snapshot_loop(every_seconds=int(args.every), count=int(args.count), write_fn=_write_once)
                if args.json:
                    print(json.dumps(res, indent=2, sort_keys=True))
                else:
                    print(json.dumps(res, indent=2, sort_keys=True))
                return 0

            # Default: existing snapshot build/write
            try:
                snapshot_as_of = _parse_as_of(getattr(args, "as_of", None))
            except ValueError as exc:
                print(str(exc))
                return 1
            return _emit_report_snapshot(
                days=args.days,
                tail=args.tail,
                strict=args.strict,
                registry_path_arg=args.registry,
                as_of=snapshot_as_of,
                include_hints=not args.no_hints,
                include_staging=args.include_staging,
                include_dev=args.include_dev,
                enforce_sla=args.enforce_sla,
                write=args.write,
                as_json=args.json,
            )
        if args.report_command == "export":
            return _emit_report_export(
                out_dir=args.out,
                days=args.days,
                tail=args.tail,
                registry_path_arg=args.registry,
                strict=bool(args.strict),
                include_staging=bool(args.include_staging),
                include_dev=bool(args.include_dev),
                enforce_sla=bool(args.enforce_sla),
                include_hints=not args.no_hints,
                ledger_path=str(args.ledger),
                n_tail=int(args.n_tail),
            )
        parser.error("Unknown report command.")


    if args.command == "failcase":
        bootstrap_repo()
        if args.failcase_command == "create":
            return _emit_failcase_create(args.mode, args.path)
        parser.error("Unknown failcase command.")

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
