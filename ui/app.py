from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

import streamlit as st

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


APP_VERSION = "0.2"
DEFAULT_PY = ".venv/bin/python"


@dataclass(frozen=True)
class CmdResult:
    rc: int
    stdout: str
    stderr: str


def _run_cmd(args: list[str]) -> CmdResult:
    """
    Read-only command runner.
    Captures stdout/stderr. Never raises on non-zero.
    """
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
        return CmdResult(rc=int(p.returncode), stdout=p.stdout or "", stderr=p.stderr or "")
    except Exception as e:
        return CmdResult(rc=99, stdout="", stderr=f"UI_CMD_ERROR: {e}")


def _safe_json_loads(s: str) -> Any | None:
    try:
        return json.loads(s)
    except Exception:
        return None


def _extract_last_json_line(stderr_text: str) -> dict[str, Any] | None:
    """
    Strict failure is emitted as one JSON line to stderr.
    We take the last non-empty line and try to parse it.
    """
    lines = [ln.strip() for ln in (stderr_text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    obj = _safe_json_loads(lines[-1])
    if isinstance(obj, dict):
        return obj
    return None


def fetch_report_health_json(
    py: str,
    registry: str | None,
    include_staging: bool,
    include_dev: bool,
    no_hints: bool,
) -> dict[str, Any] | None:
    args = [py, "-m", "app.main", "report", "health", "--json"]
    if no_hints:
        args.append("--no-hints")
    if include_staging:
        args.append("--include-staging")
    if include_dev:
        args.append("--include-dev")
    if registry:
        args.extend(["--registry", registry])
    r = _run_cmd(args)
    if r.rc != 0:
        return None
    obj = _safe_json_loads(r.stdout)
    return obj if isinstance(obj, dict) else None


def fetch_report_graph_json(py: str, registry: str | None) -> dict[str, Any] | None:
    args = [py, "-m", "app.main", "report", "graph", "--json"]
    # Support both CLI variants (compat): report graph --registry / --registry-path
    if registry:
        args.extend(["--registry", registry])
    r = _run_cmd(args)
    if r.rc != 0:
        return None
    obj = _safe_json_loads(r.stdout)
    return obj if isinstance(obj, dict) else None


def run_strict_check(
    py: str,
    registry: str | None,
    include_staging: bool,
    include_dev: bool,
    enforce_sla: bool,
) -> tuple[int, str | None, dict[str, Any] | None, str]:
    """
    Runs: health --all --strict [policy flags] [--enforce-sla]
    Returns:
      - rc (0 pass, 2 fail, 1 misuse, 99 runner error)
      - stdout_preview (optional, may be large)
      - strict_payload (parsed from stderr last json line if present)
      - raw_stderr (always returned for debugging)
    """
    args = [py, "-m", "app.main", "health", "--all", "--strict"]
    if include_staging:
        args.append("--include-staging")
    if include_dev:
        args.append("--include-dev")
    if enforce_sla:
        args.append("--enforce-sla")
    if registry:
        args.extend(["--registry", registry])

    r = _run_cmd(args)
    strict_payload = _extract_last_json_line(r.stderr)

    stdout_preview = r.stdout.strip() if r.stdout else ""
    if stdout_preview:
        # keep UI responsive
        stdout_preview = "\n".join(stdout_preview.splitlines()[:60])
    else:
        stdout_preview = None

    return r.rc, stdout_preview, strict_payload, r.stderr or ""


def _render_kv(label: str, value: Any) -> None:
    st.markdown(f"**{label}:** `{value}`")


def _render_json(obj: Any) -> None:
    st.code(json.dumps(obj, indent=2, sort_keys=True), language="json")


def _render_reasons_table(reasons: list[dict[str, Any]]) -> None:
    rows = []
    for r in reasons:
        rows.append(
            {
                "system_id": r.get("system_id"),
                "tier": r.get("tier"),
                "reason_code": r.get("reason_code"),
            }
        )
    st.table(rows)


def _policy_tiers_from_flags(include_staging: bool, include_dev: bool) -> list[str]:
    if include_dev:
        return ["prod", "staging", "dev"]
    if include_staging:
        return ["prod", "staging"]
    return ["prod"]


def _systems_status_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalizes report into a list of per-system rows.
    Supports both:
      - report["systems"]["status"] (newer)
      - report["systems"]["systems"] or report["systems"] (fallback)
    """
    systems = report.get("systems")
    if isinstance(systems, dict):
        status = systems.get("status")
        if isinstance(status, list):
            return [x for x in status if isinstance(x, dict)]
        # fallback: sometimes a report may include "systems" list under systems
        inner = systems.get("systems")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    if isinstance(systems, list):
        return [x for x in systems if isinstance(x, dict)]
    return []


def _risk_rank_map(report: dict[str, Any]) -> dict[str, int]:
    """
    risk.ranked expected as list of dicts; we convert to 1-based rank.
    """
    out: dict[str, int] = {}
    risk = report.get("risk")
    if not isinstance(risk, dict):
        return out
    ranked = risk.get("ranked")
    if not isinstance(ranked, list):
        return out
    rank = 1
    for item in ranked:
        if not isinstance(item, dict):
            continue
        sid = item.get("system_id")
        if isinstance(sid, str) and sid not in out:
            out[sid] = rank
            rank += 1
    return out


def _impact_size_proxy(report: dict[str, Any], system_id: str) -> int:
    """
    Report impact is global (sources + impacted list).
    We compute a conservative proxy:
      - if system_id is an impact source, impact_size = len(impacted)
      - else 0

    This avoids inventing per-source attribution.
    """
    impact = report.get("impact")
    if not isinstance(impact, dict):
        return 0
    sources = impact.get("sources")
    impacted = impact.get("impacted")
    if not isinstance(sources, list) or not isinstance(impacted, list):
        return 0
    if system_id in [s for s in sources if isinstance(s, str)]:
        return len([x for x in impacted if isinstance(x, dict)])
    return 0


def _owners_to_str(owners: Any) -> str:
    if isinstance(owners, list):
        xs = [str(x) for x in owners if x is not None]
        return ", ".join(xs)
    if isinstance(owners, str):
        return owners
    return ""


def _build_operator_table(report: dict[str, Any], policy_tiers: list[str]) -> list[dict[str, Any]]:
    status_rows = _systems_status_rows(report)
    risk_rank = _risk_rank_map(report)

    out: list[dict[str, Any]] = []
    for r in status_rows:
        sid = r.get("system_id")
        if not isinstance(sid, str):
            continue

        tier = r.get("tier")
        if not isinstance(tier, str):
            tier = "unknown"

        status = r.get("status")
        if not isinstance(status, str):
            status = "unknown"

        score = r.get("score_total", r.get("current_score", 0.0))
        try:
            score_f = float(score)
        except Exception:
            score_f = 0.0

        sla = r.get("sla_status")
        if not isinstance(sla, str):
            sla = "unknown"

        owners = _owners_to_str(r.get("owners"))
        impact_size = _impact_size_proxy(report, sid)
        rr = risk_rank.get(sid, 999999)

        out.append(
            {
                "system_id": sid,
                "tier": tier,
                "status": status,
                "score": round(score_f, 2),
                "sla_status": sla,
                "impact_size": int(impact_size),
                "risk_rank": int(rr),
                "owners": owners,
                "_policy_blocked": tier in set(policy_tiers),
            }
        )

    # Deterministic default sort:
    # 1) red first
    # 2) SLA breach next
    # 3) larger impact_size first
    # 4) lower risk_rank first
    # 5) system_id tie-break
    def _key(x: dict[str, Any]) -> tuple:
        status = str(x.get("status"))
        sla = str(x.get("sla_status"))
        impact = int(x.get("impact_size", 0))
        rr = int(x.get("risk_rank", 999999))
        sid = str(x.get("system_id"))
        return (
            0 if status == "red" else (1 if status == "yellow" else 2),
            0 if sla == "breach" else 1,
            -impact,
            rr,
            sid,
        )

    out.sort(key=_key)
    return out


def _render_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.info("No systems found in report payload.")
        return

    visible = []
    for r in rows:
        # hide internal helper
        rr = dict(r)
        rr.pop("_policy_blocked", None)
        visible.append(rr)

    if pd is not None:
        df = pd.DataFrame(visible)
        # Keep a stable column order
        cols = ["system_id", "tier", "status", "score", "sla_status", "impact_size", "risk_rank", "owners"]
        cols = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
        df = df[cols]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.table(visible)


def main() -> None:
    st.set_page_config(page_title="Codex Kernel UI", layout="wide")
    st.title("Codex Kernel UI (read-only)")
    st.caption(f"UI version {APP_VERSION} — deterministic, no state mutation. Uses CLI as source of truth.")

    with st.sidebar:
        st.header("Controls")
        py = st.text_input("Python executable", value=DEFAULT_PY)
        registry = st.text_input("Registry path override (optional)", value="").strip() or None

        st.subheader("Policy (strict/report)")
        include_staging = st.checkbox("Include staging in policy", value=False)
        include_dev = st.checkbox("Include dev in policy (implies staging)", value=False)
        enforce_sla = st.checkbox("Enforce SLA in strict", value=False)
        no_hints = st.checkbox("Disable report hints", value=False)

        st.subheader("Table filters")
        only_policy_tiers = st.checkbox("Show only policy tiers", value=True)
        only_red_yellow = st.checkbox("Show only red/yellow", value=False)
        only_sla_breach = st.checkbox("Show only SLA breaches", value=False)

        st.divider()
        run_now = st.button("Run refresh", type="primary")

    if include_dev:
        include_staging = True

    if not run_now:
        st.info("Click **Run refresh** to fetch report + graph + strict status.")
        return

    policy_tiers_ui = _policy_tiers_from_flags(include_staging, include_dev)

    # --- Fetch report (primary UI substrate)
    report = fetch_report_health_json(py, registry, include_staging, include_dev, no_hints)

    # --- Top row: operator table (highest ROI)
    st.subheader("Operator table")
    if report is None:
        st.error("Failed to fetch report health JSON. Check Python path, venv, and working directory.")
    else:
        rows = _build_operator_table(report, policy_tiers_ui)

        # apply filters (deterministic, no re-sorting needed)
        filtered = []
        for r in rows:
            if only_policy_tiers and not bool(r.get("_policy_blocked")):
                continue
            if only_red_yellow:
                if str(r.get("status")) not in {"red", "yellow"}:
                    continue
            if only_sla_breach:
                if str(r.get("sla_status")) != "breach":
                    continue
            filtered.append(r)

        # small KPIs
        reds = sum(1 for r in rows if str(r.get("status")) == "red")
        breaches = sum(1 for r in rows if str(r.get("sla_status")) == "breach")
        st.markdown("#### KPIs")
        c1, c2, c3 = st.columns(3)
        with c1:
            _render_kv("policy_tiers", "+".join(policy_tiers_ui))
        with c2:
            _render_kv("red_systems", reds)
        with c3:
            _render_kv("sla_breaches", breaches)

        _render_table(filtered)

        with st.expander("Full report JSON", expanded=False):
            _render_json(report)

    # --- Second row: report + graph (context)
    st.divider()
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Health report (summary)")
        if report is None:
            st.error("No report available.")
        else:
            summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
            policy = report.get("policy", {}) if isinstance(report.get("policy"), dict) else {}

            _render_kv("report_version", report.get("report_version"))
            _render_kv("now_status", summary.get("current_status"))
            _render_kv("now_score", summary.get("current_score"))
            _render_kv("strict_ready_now", summary.get("strict_ready_now"))

            st.markdown("#### Policy (from report)")
            _render_json(policy)

    with col2:
        st.subheader("Dependency graph")
        graph = fetch_report_graph_json(py, registry)
        if graph is None:
            st.error("Failed to fetch report graph JSON.")
        else:
            _render_kv("graph_version", graph.get("graph_version"))
            topo = graph.get("topo", [])
            if isinstance(topo, list):
                st.markdown("#### Topo order (first 20)")
                st.code("\n".join([str(x) for x in topo[:20]]))
            with st.expander("Full graph JSON", expanded=False):
                _render_json(graph)

    # --- Third row: strict check (live)
    st.divider()
    st.subheader("Strict check (live)")

    rc, stdout_preview, strict_payload, raw_stderr = run_strict_check(
        py=py,
        registry=registry,
        include_staging=include_staging,
        include_dev=include_dev,
        enforce_sla=enforce_sla,
    )

    st.markdown("#### Result")
    _render_kv("exit_code", rc)
    _render_kv("meaning", "PASS" if rc == 0 else ("FAIL (strict)" if rc == 2 else "ERROR/MISUSE"))

    st.markdown("#### Policy (UI)")
    _render_json(
        {
            "blocked_tiers": policy_tiers_ui,
            "include_staging": bool(include_staging),
            "include_dev": bool(include_dev),
            "enforce_sla": bool(enforce_sla),
        }
    )

    if rc == 2:
        st.error("Strict failed (exit 2). Rendering STRICT_FAILURE_SCHEMA payload from stderr.")
        if strict_payload is None:
            st.warning("No strict JSON payload found on stderr. Expand raw stderr below.")
        else:
            st.markdown("#### Strict failure payload (schema v1)")
            _render_kv("schema_version", strict_payload.get("schema_version"))
            policy = strict_payload.get("policy", {})
            reasons = strict_payload.get("reasons", [])

            st.markdown("**Policy (from strict payload)**")
            _render_json(policy)

            if isinstance(reasons, list) and reasons:
                st.markdown("**Reasons (table)**")
                _render_reasons_table(reasons)

                st.markdown("**Reasons (details)**")
                for i, r in enumerate(reasons, start=1):
                    with st.expander(f"Reason #{i}: {r.get('system_id')} — {r.get('reason_code')}", expanded=False):
                        _render_json(r)
            else:
                st.warning("Strict payload contains no reasons list.")

    else:
        st.success("Strict passed (or did not run strict failure). No strict payload expected.")

    if stdout_preview:
        with st.expander("health --all stdout preview (first 60 lines)", expanded=False):
            st.code(stdout_preview)

    if raw_stderr.strip():
        with st.expander("raw stderr (debug)", expanded=False):
            st.code(raw_stderr)


if __name__ == "__main__":
    main()
