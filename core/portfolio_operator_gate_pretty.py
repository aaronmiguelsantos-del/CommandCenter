from __future__ import annotations

from typing import Any


def _fmt_bool(x: bool) -> str:
    return "yes" if x else "no"


def _safe_int(x: Any) -> str:
    return str(x) if isinstance(x, int) else "n/a"


def render_portfolio_operator_gate_pretty(payload: dict[str, Any]) -> str:
    """
    Pretty output derived from JSON payload.
    Deterministic: stable ordering, no time calls.
    """
    lines: list[str] = []

    lines.append("PORTFOLIO OPERATOR GATE")
    lines.append("-" * 72)
    lines.append(f"exit_code: {_safe_int(payload.get('exit_code'))}")
    lines.append(f"strict_failed: {_fmt_bool(bool(payload.get('strict_failed', False)))}")
    lines.append(f"regression_detected: {_fmt_bool(bool(payload.get('regression_detected', False)))}")

    snap = payload.get("snapshot_latest") or {}
    if not isinstance(snap, dict):
        snap = {}
    lines.append("-" * 72)
    lines.append(f"captured_at: {snap.get('captured_at', 'n/a')}")
    lines.append(f"as_of: {snap.get('as_of', 'n/a')}")
    lines.append(f"portfolio_exit_code: {_safe_int(snap.get('portfolio_exit_code'))}")

    summary = snap.get("portfolio_summary") or {}
    if isinstance(summary, dict):
        lines.append(f"portfolio_status: {summary.get('portfolio_status', 'n/a')}")
        lines.append(f"portfolio_score: {_safe_int(summary.get('portfolio_score'))}")

    # Regression reasons (deterministic order as stored)
    reasons = payload.get("regression_reasons") or []
    lines.append("-" * 72)
    lines.append(f"regression_reasons: {len(reasons) if isinstance(reasons, list) else 0}")

    if isinstance(reasons, list) and reasons:
        lines.append("")
        lines.append("REASONS")
        for r in reasons:
            if not isinstance(r, dict):
                continue
            rtype = r.get("type", "UNKNOWN")
            lines.append(f"- {rtype}")

    # New top actions (from diff)
    diff = payload.get("diff_prev_latest") or {}
    if not isinstance(diff, dict):
        diff = {}
    new_actions = diff.get("new_top_actions") or []
    lines.append("-" * 72)
    lines.append(f"new_top_actions: {len(new_actions) if isinstance(new_actions, list) else 0}")

    if isinstance(new_actions, list) and new_actions:
        lines.append("")
        lines.append("TOP ACTIONS (new)")
        for a in new_actions:
            if not isinstance(a, dict):
                continue
            t = a.get("type", "ACTION")
            sys_id = a.get("system_id", "n/a")
            repo_id = a.get("repo_id", "n/a")
            repo_hash = a.get("repo_hash", "n/a")
            why = a.get("why", "")
            lines.append(f"- {t} | {repo_id}:{repo_hash} | system={sys_id} | {why}")

    lines.append("")
    return "\n".join(lines)
