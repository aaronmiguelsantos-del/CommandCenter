from __future__ import annotations

from typing import Any


PORTFOLIO_SNAPSHOT_DIFF_SCHEMA_VERSION = "1.0"


def _repo_key(r: dict[str, Any]) -> tuple[str, str]:
    repo = r.get("repo") or {}
    if not isinstance(repo, dict):
        repo = {}
    return (str(repo.get("repo_id", "")), str(repo.get("repo_hash", "")))


def _index_repos(snapshot_gate: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    repos = snapshot_gate.get("repos") or []
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(repos, list):
        return out
    for r in repos:
        if isinstance(r, dict):
            out[_repo_key(r)] = r
    return out


def _top_action_key(a: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(a.get("type", "")),
        str(a.get("system_id", "")),
        str(a.get("repo_id", "")),
        str(a.get("repo_hash", "")),
        str(a.get("why", "")),
    )


def diff_portfolio_snapshots(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_gate = a.get("portfolio_gate") or {}
    if not isinstance(a_gate, dict):
        a_gate = {}
    b_gate = b.get("portfolio_gate") or {}
    if not isinstance(b_gate, dict):
        b_gate = {}

    a_sum = a_gate.get("summary") or {}
    if not isinstance(a_sum, dict):
        a_sum = {}
    b_sum = b_gate.get("summary") or {}
    if not isinstance(b_sum, dict):
        b_sum = {}

    a_status = str(a_sum.get("portfolio_status", "unknown"))
    b_status = str(b_sum.get("portfolio_status", "unknown"))
    a_score = a_sum.get("portfolio_score")
    b_score = b_sum.get("portfolio_score")

    a_exit = a.get("portfolio_exit_code")
    b_exit = b.get("portfolio_exit_code")

    status_change = {"from": a_status, "to": b_status, "changed": a_status != b_status}

    score_delta = None
    if isinstance(a_score, int) and isinstance(b_score, int):
        score_delta = int(b_score - a_score)

    exit_change = {"from": a_exit, "to": b_exit, "changed": a_exit != b_exit}

    a_repos = _index_repos(a_gate)
    b_repos = _index_repos(b_gate)

    keys = sorted(set(a_repos.keys()) | set(b_repos.keys()))
    repos_changed: list[dict[str, Any]] = []

    for k in keys:
        ra = a_repos.get(k)
        rb = b_repos.get(k)

        # additions/removals
        if ra is None and rb is not None:
            repo = rb.get("repo") or {}
            if not isinstance(repo, dict):
                repo = {}
            repos_changed.append(
                {
                    "repo_id": repo.get("repo_id"),
                    "repo_hash": repo.get("repo_hash"),
                    "change": "added",
                }
            )
            continue
        if rb is None and ra is not None:
            repo = ra.get("repo") or {}
            if not isinstance(repo, dict):
                repo = {}
            repos_changed.append(
                {
                    "repo_id": repo.get("repo_id"),
                    "repo_hash": repo.get("repo_hash"),
                    "change": "removed",
                }
            )
            continue

        assert ra is not None and rb is not None
        ga = ra.get("gate") or {}
        if not isinstance(ga, dict):
            ga = {}
        gb = rb.get("gate") or {}
        if not isinstance(gb, dict):
            gb = {}

        fields = {
            "repo_status": (ra.get("repo_status"), rb.get("repo_status")),
            "error_code": (ra.get("error_code"), rb.get("error_code")),
            "exit_code": (ra.get("exit_code"), rb.get("exit_code")),
            "strict_failed": (bool(ga.get("strict_failed", False)), bool(gb.get("strict_failed", False))),
            "regression_detected": (bool(ga.get("regression_detected", False)), bool(gb.get("regression_detected", False))),
        }

        changed_fields = {k2: {"from": v[0], "to": v[1]} for k2, v in fields.items() if v[0] != v[1]}
        if changed_fields:
            repo = rb.get("repo") or {}
            if not isinstance(repo, dict):
                repo = {}
            repos_changed.append(
                {
                    "repo_id": repo.get("repo_id"),
                    "repo_hash": repo.get("repo_hash"),
                    "change": "modified",
                    "fields": changed_fields,
                }
            )

    # New top actions since A -> B
    a_actions_raw = a_gate.get("top_actions") or []
    b_actions_raw = b_gate.get("top_actions") or []
    a_actions = {_top_action_key(x): x for x in a_actions_raw if isinstance(x, dict)}
    b_actions = {_top_action_key(x): x for x in b_actions_raw if isinstance(x, dict)}
    new_keys = sorted(set(b_actions.keys()) - set(a_actions.keys()))
    new_actions = [b_actions[k] for k in new_keys]

    return {
        "schema_version": PORTFOLIO_SNAPSHOT_DIFF_SCHEMA_VERSION,
        "a": {"captured_at": a.get("captured_at"), "as_of": a.get("as_of"), "portfolio_exit_code": a_exit},
        "b": {"captured_at": b.get("captured_at"), "as_of": b.get("as_of"), "portfolio_exit_code": b_exit},
        "portfolio_status_change": status_change,
        "portfolio_score_delta": score_delta,
        "portfolio_exit_code_change": exit_change,
        "repos_changed": repos_changed,
        "new_top_actions": new_actions,
    }
