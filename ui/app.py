from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import streamlit as st

try:
    from ui.cli_cmds import (
        PolicyFlags,
        SnapshotFlags,
        build_health_all_cmd,
        build_report_graph_cmd,
        build_report_health_cmd,
        build_report_snapshot_diff_cmd,
        build_report_snapshot_run_cmd,
        build_report_snapshot_stats_cmd,
        build_report_snapshot_tail_cmd,
    )
except ModuleNotFoundError:
    # Supports streamlit execution when cwd is ui/ (no package prefix on sys.path).
    from cli_cmds import (
        PolicyFlags,
        SnapshotFlags,
        build_health_all_cmd,
        build_report_graph_cmd,
        build_report_health_cmd,
        build_report_snapshot_diff_cmd,
        build_report_snapshot_run_cmd,
        build_report_snapshot_stats_cmd,
        build_report_snapshot_tail_cmd,
    )

# -----------------------------
# UI META
# -----------------------------
UI_VERSION = "0.5"
DEFAULT_REGISTRY = "data/registry/systems.json"
DEFAULT_LEDGER = "data/snapshots/report_snapshot_history.jsonl"


# -----------------------------
# SMALL UTILITIES
# -----------------------------
def _is_probably_json(text: str) -> bool:
    t = (text or "").strip()
    return (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))


def _safe_json_loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        return None


def _root_cwd() -> Path:
    # UI is launched from repo root via ./ui/run_ui.sh; still guard.
    return Path(os.getcwd())


def _python_bin() -> str:
    # Prefer repo venv python if present.
    repo = _root_cwd()
    venv_py = repo / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return "python3"


@dataclass(frozen=True)
class CmdResult:
    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


def run_cli(argv: list[str], timeout_sec: int = 30) -> CmdResult:
    """
    Runs the CLI and returns stdout/stderr. Never raises.
    """
    # Accept either:
    # - app args: ["health", "--all", ...]
    # - full cmd: [python, "-m", "app.main", "health", "--all", ...]
    if len(argv) >= 3 and argv[1] == "-m" and argv[2] == "app.main":
        full = argv
    else:
        py = _python_bin()
        full = [py, "-m", "app.main", *argv]
    try:
        p = subprocess.run(
            full,
            cwd=str(_root_cwd()),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return CmdResult(
            returncode=int(p.returncode),
            stdout=p.stdout or "",
            stderr=p.stderr or "",
            argv=full,
        )
    except subprocess.TimeoutExpired as exc:
        return CmdResult(
            returncode=124,
            stdout=(exc.stdout or "") if hasattr(exc, "stdout") else "",
            stderr="TIMEOUT",
            argv=full,
        )
    except Exception as exc:
        return CmdResult(
            returncode=1,
            stdout="",
            stderr=f"RUN_ERROR: {type(exc).__name__}: {exc}",
            argv=full,
        )


def show_cmd_debug(res: CmdResult) -> None:
    with st.expander("Command debug", expanded=False):
        st.code(" ".join(res.argv))
        st.write(f"exit={res.returncode}")
        if res.stderr.strip():
            st.subheader("stderr")
            st.code(res.stderr)
        if res.stdout.strip():
            st.subheader("stdout")
            st.code(res.stdout)


def show_json_or_text(title: str, res: CmdResult) -> None:
    st.subheader(title)
    if res.returncode not in (0, 2):  # 2 is strict failure by design
        st.error(f"Command failed (exit={res.returncode}).")
        show_cmd_debug(res)
        return

    out = (res.stdout or "").strip()
    if _is_probably_json(out):
        payload = _safe_json_loads(out)
        if payload is not None:
            st.json(payload)
        else:
            st.code(out)
    else:
        st.code(out)

    # show strict stderr payload (one-line JSON) if present
    if res.stderr.strip():
        st.caption("stderr (strict failure payload / diagnostics)")
        st.code(res.stderr.strip())

    show_cmd_debug(res)


def _extract_health_system_rows(res: CmdResult) -> list[dict[str, Any]]:
    if res.returncode not in (0, 2):
        return []
    payload = _safe_json_loads((res.stdout or "").strip())
    if not isinstance(payload, dict):
        return []
    rows = payload.get("systems", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _extract_report_system_status_rows(res: CmdResult) -> list[dict[str, Any]]:
    if res.returncode not in (0, 2):
        return []
    payload = _safe_json_loads((res.stdout or "").strip())
    if not isinstance(payload, dict):
        return []
    systems = payload.get("systems", {})
    if not isinstance(systems, dict):
        return []
    rows = systems.get("status", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


# -----------------------------
# ARG BUILDERS (PARITY IS HERE)
# -----------------------------
def build_policy_args(include_staging: bool, include_dev: bool) -> list[str]:
    args: list[str] = []
    if include_staging:
        args.append("--include-staging")
    if include_dev:
        args.append("--include-dev")
    return args


def build_registry_args(registry_path: str) -> list[str]:
    p = (registry_path or "").strip()
    if not p:
        return []
    return ["--registry", p]


def build_report_health_args(
    *,
    registry_path: str,
    days: int,
    tail: int,
    strict: bool,
    enforce_sla: bool,
    include_staging: bool,
    include_dev: bool,
    include_hints: bool,
    as_json: bool,
) -> list[str]:
    args = ["report", "health", "--days", str(int(days)), "--tail", str(int(tail))]
    if as_json:
        args.append("--json")
    if strict:
        args.append("--strict")
    if strict and enforce_sla:
        # IMPORTANT: parity fix — only meaningful with strict, but harmless if passed.
        args.append("--enforce-sla")
    args += build_policy_args(include_staging, include_dev)
    if not include_hints:
        args.append("--no-hints")
    args += build_registry_args(registry_path)
    return args


def build_report_graph_args(*, registry_path: str, as_json: bool) -> list[str]:
    args = ["report", "graph"]
    if as_json:
        args.append("--json")
    args += build_registry_args(registry_path)
    return args


def build_health_all_strict_args(
    *,
    registry_path: str,
    strict: bool,
    enforce_sla: bool,
    include_staging: bool,
    include_dev: bool,
    hide_samples: bool,
    as_json: bool,
) -> list[str]:
    args = ["health", "--all"]
    if as_json:
        args.append("--json")
    args += build_registry_args(registry_path)
    args += build_policy_args(include_staging, include_dev)
    if strict:
        args.append("--strict")
    if strict and enforce_sla:
        args.append("--enforce-sla")
    if hide_samples:
        args.append("--hide-samples")
    return args


def build_report_snapshot_write_args(
    *,
    registry_path: str,
    days: int,
    tail: int,
    strict: bool,
    enforce_sla: bool,
    include_staging: bool,
    include_dev: bool,
    include_hints: bool,
) -> list[str]:
    args = ["report", "snapshot", "--write", "--json", "--days", str(int(days)), "--tail", str(int(tail))]
    if strict:
        args.append("--strict")
    if strict and enforce_sla:
        args.append("--enforce-sla")
    args += build_policy_args(include_staging, include_dev)
    if not include_hints:
        args.append("--no-hints")
    args += build_registry_args(registry_path)
    return args


def build_report_snapshot_tail_args(*, ledger: str, n: int) -> list[str]:
    args = ["report", "snapshot", "tail", "--json", "--ledger", ledger, "--n", str(int(n))]
    return args


def build_report_snapshot_stats_args(*, ledger: str, days: int) -> list[str]:
    args = ["report", "snapshot", "stats", "--json", "--ledger", ledger, "--days", str(int(days))]
    return args


def build_report_snapshot_run_args(*, every: int, count: int, as_json: bool) -> list[str]:
    args = ["report", "snapshot", "run", "--every", str(int(every)), "--count", str(int(count))]
    if as_json:
        args.append("--json")
    return args


def build_validate_args(*, registry_path: str) -> list[str]:
    # validate supports --registry in your CLI
    args = ["validate"]
    args += build_registry_args(registry_path)
    return args


def build_failcase_create_args(*, path: str, mode: str) -> list[str]:
    return ["failcase", "create", "--path", path, "--mode", mode]


# -----------------------------
# STREAMLIT APP
# -----------------------------
st.set_page_config(page_title=f"Bootstrapping Engine UI v{UI_VERSION}", layout="wide")

st.title(f"Bootstrapping Engine — UI v{UI_VERSION}")
st.caption("Read-first operator console. Strict/report parity is enforced by construction.")

with st.sidebar:
    st.header("Mode")
    mode = st.selectbox("UI mode", ["Read", "Ops", "Dev"], index=0)

    st.divider()
    st.header("Inputs")

    registry_path = st.text_input("Registry path", value=DEFAULT_REGISTRY)
    ledger_path = st.text_input("Snapshot ledger", value=DEFAULT_LEDGER)

    st.divider()
    st.header("Policy")
    colp1, colp2 = st.columns(2)
    with colp1:
        include_staging = st.checkbox("Include staging", value=False)
    with colp2:
        include_dev = st.checkbox("Include dev", value=False)

    strict = st.checkbox("Strict", value=False)
    enforce_sla = st.checkbox("Enforce SLA (strict)", value=False, help="Only applies when Strict is enabled.")
    show_samples = st.toggle("Show sample systems", value=False)

    st.divider()
    st.header("Report settings")
    colr1, colr2, colr3 = st.columns(3)
    with colr1:
        days = st.number_input("Days", min_value=1, max_value=365, value=30, step=1)
    with colr2:
        tail = st.number_input("Tail (history lines)", min_value=1, max_value=200000, value=2000, step=100)
    with colr3:
        include_hints = st.checkbox("Include hints", value=True)

    st.divider()
    st.header("Quick actions")
    if st.button("Refresh now", width="stretch"):
        st.session_state["_refresh"] = time.time()

# Enforce implied policy: include_dev implies staging
if include_dev and not include_staging:
    include_staging = True

# Enforce enforce_sla only with strict (but keep UI state visible)
effective_enforce_sla = bool(strict and enforce_sla)
hide_samples = not bool(show_samples)

policy = PolicyFlags(
    strict=bool(strict),
    enforce_sla=bool(effective_enforce_sla),
    include_staging=bool(include_staging),
    include_dev=bool(include_dev),
    hide_samples=bool(hide_samples),
)

# -----------------------------
# TOP ROW: STRICT CHECK + REPORT HEALTH (PARITY)
# -----------------------------
left, right = st.columns(2, gap="large")

with left:
    st.subheader("Strict gate (health --all)")
    strict_args = build_health_all_cmd(
        cli_python=_python_bin(),
        registry_path=registry_path.strip() or None,
        policy=policy,
        as_json=True,
    )
    res_strict = run_cli(strict_args, timeout_sec=30)
    show_json_or_text("health --all output (json)", res_strict)
    strict_rows = _extract_health_system_rows(res_strict)
    strict_suffix = " (samples hidden)" if hide_samples else ""
    st.caption(f"Showing {len(strict_rows)} systems{strict_suffix}")
    if strict_rows:
        st.caption("Strict systems")
        st.dataframe(strict_rows, width="stretch")

with right:
    st.subheader("Report health (report health --json)")
    report_args = build_report_health_cmd(
        cli_python=_python_bin(),
        registry_path=registry_path.strip() or None,
        policy=policy,
        days=int(days),
        tail=int(tail),
        include_hints=bool(include_hints),
        as_json=True,
    )
    res_report = run_cli(report_args, timeout_sec=60)
    show_json_or_text("report health output (json)", res_report)
    report_rows = _extract_report_system_status_rows(res_report)
    report_total = len(report_rows)
    filtered_report_rows = report_rows
    if hide_samples:
        filtered_report_rows = [row for row in report_rows if not row.get("is_sample")]
    suffix = " (samples hidden)" if hide_samples else ""
    st.caption(f"Showing {len(filtered_report_rows)} / {report_total} systems{suffix}")
    if filtered_report_rows:
        st.caption("Report systems (filtered)")
        st.dataframe(filtered_report_rows, width="stretch")

st.divider()

# -----------------------------
# READ MODE CONTENT
# -----------------------------
if mode in ("Read", "Ops", "Dev"):
    tab1, tab2, tab3 = st.tabs(["Graph", "Snapshots", "Export/Raw"])

    with tab1:
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.subheader("Graph (json)")
            res_graph_json = run_cli(
                build_report_graph_cmd(
                    cli_python=_python_bin(),
                    registry_path=registry_path.strip() or None,
                    as_json=True,
                ),
                timeout_sec=30,
            )
            show_json_or_text("report graph --json", res_graph_json)
        with c2:
            st.subheader("Graph (text)")
            res_graph_txt = run_cli(
                build_report_graph_cmd(
                    cli_python=_python_bin(),
                    registry_path=registry_path.strip() or None,
                    as_json=False,
                ),
                timeout_sec=30,
            )
            show_json_or_text("report graph (text)", res_graph_txt)

    with tab2:
        st.subheader("Snapshots")
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        with col_s1:
            n_tail_rows = st.number_input("Tail rows", min_value=1, max_value=300, value=20, step=1)
        with col_s2:
            stats_days = st.number_input("Stats days", min_value=1, max_value=365, value=7, step=1)
        with col_s3:
            diff_a = st.text_input("Diff A ref", value="prev")
        with col_s4:
            diff_b = st.text_input("Diff B ref", value="latest")

        st.caption("Ledger path")
        st.code(ledger_path)

        snap_flags = SnapshotFlags(
            ledger=ledger_path,
            tail=int(tail),
            days=int(stats_days),
            strict=bool(strict),
            enforce_sla=bool(effective_enforce_sla),
            include_staging=bool(include_staging),
            include_dev=bool(include_dev),
        )

        st.write("Current policy toggles")
        st.json(
            {
                "strict": bool(snap_flags.strict),
                "enforce_sla": bool(snap_flags.enforce_sla),
                "include_staging": bool(snap_flags.include_staging),
                "include_dev": bool(snap_flags.include_dev),
                "hide_samples": bool(policy.hide_samples),
            }
        )

        # Tail
        st.markdown("### Tail")
        tail_btn = st.button("Refresh tail", width="stretch")
        if tail_btn or True:
            res_tail = run_cli(
                build_report_snapshot_tail_cmd(
                    snap_flags,
                    n=int(n_tail_rows),
                    registry=registry_path.strip() or None,
                    cli_python=_python_bin(),
                ),
                timeout_sec=30,
            )
            show_json_or_text("report snapshot tail --json", res_tail)
            tail_payload = _safe_json_loads((res_tail.stdout or "").strip())
            if isinstance(tail_payload, list):
                rows: list[dict[str, Any]] = []
                for r in tail_payload:
                    if not isinstance(r, dict):
                        continue
                    systems = r.get("systems", [])
                    systems_count = len(systems) if isinstance(systems, list) else 0
                    sf = r.get("strict_failure")
                    strict_failed = bool(isinstance(sf, dict) and sf.get("strict_failed", True))
                    reason_codes: list[str] = []
                    if isinstance(sf, dict):
                        reasons = sf.get("reasons", [])
                        if isinstance(reasons, list):
                            reason_codes = sorted(
                                {
                                    str(x.get("reason_code", ""))
                                    for x in reasons
                                    if isinstance(x, dict)
                                }
                            )
                    summary = r.get("summary", {})
                    strict_ready_now = summary.get("strict_ready_now") if isinstance(summary, dict) else None
                    rows.append(
                        {
                            "ts": str(r.get("ts", "")),
                            "systems_count": systems_count,
                            "strict_failed": strict_failed,
                            "reason_codes": ",".join(reason_codes) if reason_codes else "",
                            "strict_ready_now": strict_ready_now,
                        }
                    )

                st.caption(f"Showing {len(rows)} / {len(tail_payload)} snapshots")
                st.dataframe(rows, width="stretch")

                if tail_payload and isinstance(tail_payload[-1], dict):
                    embedded_policy = tail_payload[-1].get("policy")
                    if isinstance(embedded_policy, dict):
                        st.write("Latest embedded snapshot policy")
                        st.json(embedded_policy)

                with st.expander("View JSON", expanded=False):
                    st.json(tail_payload)

        # Stats
        st.markdown("### Stats")
        stats_btn = st.button("Refresh stats", width="stretch")
        if stats_btn or True:
            res_stats = run_cli(
                build_report_snapshot_stats_cmd(
                    snap_flags,
                    registry=registry_path.strip() or None,
                    cli_python=_python_bin(),
                ),
                timeout_sec=30,
            )
            show_json_or_text("report snapshot stats --json", res_stats)
            stats_payload = _safe_json_loads((res_stats.stdout or "").strip())
            if isinstance(stats_payload, dict):
                c1, c2, c3 = st.columns(3)
                c1.metric("rows/total", str(stats_payload.get("rows", stats_payload.get("total", 0))))
                c2.metric("strict_failures/rate", str(stats_payload.get("strict_failures", stats_payload.get("strict_ready_rate", 0))))
                c3.metric("days", str(stats_payload.get("days", stats_days)))

                if isinstance(stats_payload.get("top_system_reasons"), list):
                    st.write("Top movers")
                    st.dataframe(stats_payload.get("top_system_reasons"), width="stretch")
                elif isinstance(stats_payload.get("top_reasons"), list):
                    st.write("Top movers")
                    st.dataframe(stats_payload.get("top_reasons"), width="stretch")
                elif isinstance(stats_payload.get("reason_codes"), dict):
                    st.write("Top movers")
                    st.dataframe(
                        [{"reason_code": k, "count": v} for k, v in stats_payload.get("reason_codes", {}).items()],
                        width="stretch",
                    )

        # Diff
        st.markdown("### Diff")
        diff_btn = st.button("Diff prev→latest", width="stretch")
        if diff_btn or True:
            res_diff = run_cli(
                build_report_snapshot_diff_cmd(
                    snap_flags,
                    a=diff_a.strip() or "prev",
                    b=diff_b.strip() or "latest",
                    registry=registry_path.strip() or None,
                    cli_python=_python_bin(),
                ),
                timeout_sec=30,
            )
            show_json_or_text("report snapshot diff --json", res_diff)
            diff_payload = _safe_json_loads((res_diff.stdout or "").strip())
            diff_obj = diff_payload.get("diff", {}) if isinstance(diff_payload, dict) else {}
            if isinstance(diff_obj, dict):
                st.write("Status changes")
                st.dataframe(diff_obj.get("system_status_changes", []), width="stretch")
                st.write("New strict reasons")
                st.dataframe(diff_obj.get("new_strict_reasons", []), width="stretch")
                st.write("Risk rank delta (top movers)")
                st.dataframe(diff_obj.get("risk_rank_delta_top", []), width="stretch")

    with tab3:
        st.subheader("Raw outputs")
        st.caption("This tab is for quick troubleshooting when something looks off.")
        st.write(
            {
                "ui_version": UI_VERSION,
                "cwd": str(_root_cwd()),
                "python": _python_bin(),
                "registry_path": registry_path,
                "ledger_path": ledger_path,
                "policy": {
                    "include_staging": bool(include_staging),
                    "include_dev": bool(include_dev),
                    "strict": bool(strict),
                    "enforce_sla": bool(effective_enforce_sla),
                },
            }
        )

st.divider()

# -----------------------------
# OPS MODE: SAFE OPERATOR BUTTONS
# -----------------------------
if mode in ("Ops", "Dev"):
    st.header("Ops actions")

    op1, op2, op3 = st.columns(3, gap="large")

    with op1:
        st.subheader("Validate")
        if st.button("Run validate", width="stretch"):
            res_val = run_cli(build_validate_args(registry_path=registry_path), timeout_sec=60)
            show_json_or_text("validate output", res_val)

    with op2:
        st.subheader("Write snapshot")
        st.caption("Appends to ledger via `report snapshot --write --json`.")
        if st.button("Write snapshot now", width="stretch"):
            res_write = run_cli(
                build_report_snapshot_write_args(
                    registry_path=registry_path,
                    days=int(days),
                    tail=int(tail),
                    strict=bool(strict),
                    enforce_sla=bool(effective_enforce_sla),
                    include_staging=bool(include_staging),
                    include_dev=bool(include_dev),
                    include_hints=bool(include_hints),
                ),
                timeout_sec=60,
            )
            show_json_or_text("snapshot write payload", res_write)

    with op3:
        st.subheader("Failcase (tmp)")
        st.caption("Creates a deterministic repo under /tmp for demos.")
        fc_mode = st.selectbox("Failcase mode", ["sla-breach", "red-status", "clean"], index=0)
        fc_path = st.text_input("Failcase path", value="/tmp/codex-kernel-failcase")
        if st.button("Create failcase", width="stretch"):
            res_fc = run_cli(build_failcase_create_args(path=fc_path, mode=fc_mode), timeout_sec=30)
            show_json_or_text("failcase create", res_fc)

    st.divider()
    st.subheader("Snapshot run loop")
    col_loop1, col_loop2, col_loop3 = st.columns(3)
    with col_loop1:
        every = st.number_input("Every (seconds)", min_value=1, max_value=300, value=5, step=1)
    with col_loop2:
        count = st.number_input("Count", min_value=1, max_value=50, value=3, step=1)
    with col_loop3:
        run_json = st.checkbox("Emit JSON", value=True)

    if st.button("Run loop now", width="stretch"):
        loop_flags = SnapshotFlags(
            ledger=ledger_path,
            tail=int(tail),
            days=int(days),
            strict=bool(strict),
            enforce_sla=bool(effective_enforce_sla),
            include_staging=bool(include_staging),
            include_dev=bool(include_dev),
        )
        res_loop = run_cli(
            build_report_snapshot_run_cmd(loop_flags, every=int(every), count=int(count), cli_python=_python_bin()),
            timeout_sec=300,
        )
        show_json_or_text("report snapshot run", res_loop)

# -----------------------------
# DEV MODE: MUTATIONS (HARD-GATED)
# -----------------------------
if mode == "Dev":
    st.header("Dev mutations (guarded)")
    st.warning("These mutate repo state. Keep off unless you mean it.")

    armed = st.checkbox("I know what I'm doing (arm mutations)", value=False)
    if armed:
        st.caption("Mutations are intentionally not implemented in v0.4. Add in v0.5+ only if you really need them.")
        st.info("Planned: system add / contract new / log. (Not wired here yet.)")
