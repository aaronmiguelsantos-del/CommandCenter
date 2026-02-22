from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from core.portfolio_snapshot import capture_portfolio_snapshot, write_portfolio_snapshot, _filter_as_of, _read_jsonl, _ref_select
from core.portfolio_snapshot_diff import diff_portfolio_snapshots, worsened_exit_code, worsened_status


PORTFOLIO_OPERATOR_GATE_SCHEMA_VERSION = "1.0"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_bundle_meta(export_dir: Path, artifacts: list[str]) -> None:
    meta = {"schema_version": "1.0", "artifacts": artifacts}
    _write_json(export_dir / "bundle_meta.json", meta)


def _detect_regression(diff: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic regression detector from diff payload.
    """
    reasons: list[dict[str, Any]] = []

    ps = diff.get("portfolio_status_change") or {}
    if isinstance(ps, dict) and bool(ps.get("changed", False)):
        if worsened_status(str(ps.get("from")), str(ps.get("to"))):
            reasons.append({"type": "PORTFOLIO_STATUS_WORSENED", "details": ps})

    pe = diff.get("portfolio_exit_code_change") or {}
    if isinstance(pe, dict) and bool(pe.get("changed", False)):
        a = pe.get("from")
        b = pe.get("to")
        if isinstance(a, int) and isinstance(b, int) and worsened_exit_code(a, b):
            reasons.append({"type": "PORTFOLIO_EXIT_CODE_WORSENED", "details": pe})

    repos_changed = diff.get("repos_changed") or []
    if isinstance(repos_changed, list) and repos_changed:
        reasons.append({"type": "REPOS_CHANGED", "details": {"count": len(repos_changed)}})

    new_actions = diff.get("new_top_actions") or []
    if isinstance(new_actions, list) and new_actions:
        reasons.append({"type": "NEW_TOP_ACTIONS", "details": {"count": len(new_actions)}})

    return {"regression_detected": bool(reasons), "regression_reasons": reasons}


def _exit_code(latest_portfolio_exit: int, regression_detected: bool) -> int:
    strict_failed = latest_portfolio_exit in (2, 4)
    if strict_failed and regression_detected:
        return 4
    if strict_failed:
        return 2
    if regression_detected:
        return 3
    return 0


def run_portfolio_operator_gate(
    *,
    ledger_path: str,
    repos: Optional[list[str]],
    repos_file: Optional[str],
    repos_map: Optional[str],
    allow_missing: bool,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: Optional[str],
    jobs: int,
    fail_fast: bool,
    max_repos: Optional[int],
    export_mode: str,
    captured_at: Optional[str],
    export_path: Optional[str],
) -> tuple[dict[str, Any], int]:
    # 1) Capture + write latest snapshot
    snap = capture_portfolio_snapshot(
        repos=repos,
        repos_file=repos_file,
        repos_map=repos_map,
        allow_missing=allow_missing,
        hide_samples=hide_samples,
        strict=strict,
        enforce_sla=enforce_sla,
        as_of=as_of,
        jobs=jobs,
        fail_fast=fail_fast,
        max_repos=max_repos,
        export_mode=export_mode,
        captured_at=captured_at,
    )
    snap = write_portfolio_snapshot(ledger_path=ledger_path, snapshot=snap)

    # 2) Load ledger + diff prev -> latest (if prev exists)
    rows = _read_jsonl(Path(ledger_path).expanduser().resolve())
    rows = _filter_as_of(rows, as_of)

    has_prev = len(rows) >= 2
    if has_prev:
        a = _ref_select(rows, "prev")
        b = _ref_select(rows, "latest")
        d = diff_portfolio_snapshots(a, b)
        reg = _detect_regression(d)
    else:
        # No prev means no regression by definition; deterministic.
        d = {
            "schema_version": "1.0",
            "a": None,
            "b": {
                "captured_at": snap.get("captured_at"),
                "as_of": snap.get("as_of"),
                "portfolio_exit_code": snap.get("portfolio_exit_code"),
            },
            "portfolio_status_change": {"from": None, "to": None, "changed": False},
            "portfolio_score_delta": None,
            "portfolio_exit_code_change": {"from": None, "to": None, "changed": False},
            "repos_changed": [],
            "new_top_actions": [],
            "note": "no prev snapshot; regression detection skipped",
        }
        reg = {"regression_detected": False, "regression_reasons": []}

    latest_exit = int(snap.get("portfolio_exit_code", 0))
    exit_code = _exit_code(latest_exit, bool(reg["regression_detected"]))

    payload: dict[str, Any] = {
        "schema_version": PORTFOLIO_OPERATOR_GATE_SCHEMA_VERSION,
        "command": "portfolio_operator_gate",
        "exit_code": int(exit_code),
        "strict_failed": latest_exit in (2, 4),
        "regression_detected": bool(reg["regression_detected"]),
        "policy": {
            "ledger": ledger_path,
            "repos": repos,
            "repos_file": repos_file,
            "repos_map": repos_map,
            "allow_missing": bool(allow_missing),
            "hide_samples": bool(hide_samples),
            "strict": bool(strict),
            "enforce_sla": bool(enforce_sla),
            "as_of": as_of,
            "jobs": int(jobs),
            "fail_fast": bool(fail_fast),
            "max_repos": max_repos,
            "export_mode": export_mode,
            "captured_at": captured_at,
        },
        "snapshot_latest": {
            "captured_at": snap.get("captured_at"),
            "as_of": snap.get("as_of"),
            "portfolio_exit_code": latest_exit,
            "portfolio_summary": ((snap.get("portfolio_gate") or {}).get("summary") or {}),
        },
        "diff_prev_latest": d,
        "regression_reasons": reg["regression_reasons"],
        "artifacts": {"exported": bool(export_path)},
    }

    if export_path:
        export_dir = Path(export_path).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)

        artifacts = [
            "bundle_meta.json",
            "portfolio_operator_gate.json",
            "portfolio_snapshot_latest.json",
            "portfolio_snapshot_diff.json",
        ]

        _write_json(export_dir / "portfolio_operator_gate.json", payload)
        _write_json(export_dir / "portfolio_snapshot_latest.json", snap)
        _write_json(export_dir / "portfolio_snapshot_diff.json", d)
        _write_bundle_meta(export_dir, artifacts)

    return payload, exit_code
