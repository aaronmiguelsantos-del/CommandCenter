from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Phase 2 (v3.3.x) Portfolio Gate Contract
PORTFOLIO_GATE_SCHEMA_VERSION = "1.0"

_VALID_GATE_EXIT_CODES = {0, 2, 3, 4}
_SEVERITY_RANK = {
    "STRICT_REGRESSION": 1,
    "STATUS_REGRESSION": 2,
    "RISK_INCREASE": 3,
    "NEW_HIGH_VIOLATIONS": 4,
}


@dataclass(frozen=True)
class RepoSpec:
    repo_id: str
    repo_hash: str
    repo_root: str
    registry_path: str


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _normalize_path(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def _engine_root() -> str:
    # core/portfolio_gate.py -> core -> repo root
    return str(Path(__file__).resolve().parents[1])


def _parse_repos_file(path: str) -> list[str]:
    p = Path(path).expanduser().resolve()
    lines: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _infer_repo_root_and_registry(path_str: str) -> tuple[str, str]:
    """
    Accept either:
    - repo root path -> registry assumed at <repo>/data/registry/systems.json
    - registry json  -> registry is that file; repo_root inferred if it matches .../data/registry/systems.json
    """
    p = Path(_normalize_path(path_str))
    if p.is_file() and p.suffix.lower() == ".json":
        registry = str(p)
        parts = list(p.parts)
        if "data" in parts and "registry" in parts:
            try:
                data_i = parts.index("data")
                repo_root = str(Path(*parts[:data_i]))
            except Exception:
                repo_root = str(p.parent)
        else:
            repo_root = str(p.parent)
        return repo_root, registry

    repo_root = str(p)
    registry = str(Path(repo_root) / "data" / "registry" / "systems.json")
    return repo_root, registry


def _repo_spec(path_str: str) -> RepoSpec:
    repo_root, registry = _infer_repo_root_and_registry(path_str)
    repo_root_abs = _normalize_path(repo_root)
    registry_abs = _normalize_path(registry)

    base = Path(repo_root_abs).name or repo_root_abs
    h = _sha256(repo_root_abs)[:12]

    return RepoSpec(
        repo_id=base,
        repo_hash=h,
        repo_root=repo_root_abs,
        registry_path=registry_abs,
    )


def _stable_strict_reasons(reasons: Any) -> list[dict[str, Any]]:
    if not isinstance(reasons, list):
        return []
    out = [r for r in reasons if isinstance(r, dict)]
    out.sort(
        key=lambda r: (
            str(r.get("reason_code", "")),
            str(r.get("tier", "")),
            str(r.get("system_id", "")),
            json.dumps(r, sort_keys=True),
        )
    )
    return out


def _stable_top_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        return []
    out = [a for a in actions if isinstance(a, dict)]
    out.sort(
        key=lambda a: (
            int(_SEVERITY_RANK.get(str(a.get("type", "")), 99)),
            str(a.get("system_id", "")),
            str(a.get("type", "")),
            json.dumps(a, sort_keys=True),
        )
    )
    for i, a in enumerate(out, start=1):
        a["priority"] = i
    return out


def _stable_gate_payload(gate_payload: dict[str, Any], gate_exit_code: int) -> dict[str, Any]:
    strict_failed = bool(gate_payload.get("strict_failed", False)) or gate_exit_code in {2, 4}
    regression_detected = bool(gate_payload.get("regression_detected", False)) or gate_exit_code in {3, 4}
    return {
        "command": str(gate_payload.get("command", "operator_gate")),
        "schema_version": str(gate_payload.get("schema_version", "1.0")),
        "exit_code": int(gate_payload.get("exit_code", gate_exit_code)),
        "strict_failed": strict_failed,
        "regression_detected": regression_detected,
        "top_actions": _stable_top_actions(gate_payload.get("top_actions")),
        "strict_reasons": _stable_strict_reasons(gate_payload.get("strict_reasons")),
    }


def _run_operator_gate_for_repo(
    spec: RepoSpec,
    *,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: str | None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "app.main",
        "operator",
        "gate",
        "--json",
        "--registry",
        spec.registry_path,
    ]
    if hide_samples:
        cmd.append("--hide-samples")
    if strict:
        cmd.append("--strict")
    if enforce_sla:
        cmd.append("--enforce-sla")
    if as_of:
        cmd.extend(["--as-of", as_of])

    env = dict(os.environ)
    engine_root = _engine_root()
    env["PYTHONPATH"] = engine_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    try:
        p = subprocess.run(
            cmd,
            cwd=spec.repo_root,
            capture_output=True,
            text=True,
            env=env,
        )
    except Exception as exc:
        return {
            "repo": {
                "repo_id": spec.repo_id,
                "repo_hash": spec.repo_hash,
                "repo_root": spec.repo_root,
                "registry_path": spec.registry_path,
            },
            "exit_code": 1,
            "gate": _stable_gate_payload({}, 1),
            "stderr": f"RUN_ERROR: {type(exc).__name__}: {exc}",
        }

    stdout = (p.stdout or "").strip()
    gate_payload: dict[str, Any] = {}
    if stdout:
        try:
            decoded = json.loads(stdout)
            if isinstance(decoded, dict):
                gate_payload = decoded
        except Exception:
            gate_payload = {}

    return {
        "repo": {
            "repo_id": spec.repo_id,
            "repo_hash": spec.repo_hash,
            "repo_root": spec.repo_root,
            "registry_path": spec.registry_path,
        },
        "exit_code": int(p.returncode),
        "gate": _stable_gate_payload(gate_payload, int(p.returncode)),
        "stderr": (p.stderr or "").strip(),
    }


def _portfolio_exit_code(repo_results: list[dict[str, Any]]) -> int:
    if any(int(r.get("exit_code", 1)) not in _VALID_GATE_EXIT_CODES for r in repo_results):
        return 1

    strict_failed_any = False
    regression_any = False
    for r in repo_results:
        gate = r.get("gate") or {}
        if bool(gate.get("strict_failed", False)):
            strict_failed_any = True
        if bool(gate.get("regression_detected", False)):
            regression_any = True

    if strict_failed_any and regression_any:
        return 4
    if strict_failed_any:
        return 2
    if regression_any:
        return 3
    return 0


def _merge_top_actions(repo_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for rr in repo_results:
        repo = rr.get("repo") or {}
        repo_id = str(repo.get("repo_id", ""))
        repo_hash = str(repo.get("repo_hash", ""))
        gate = rr.get("gate") or {}
        for a in gate.get("top_actions") or []:
            if not isinstance(a, dict):
                continue
            aa = dict(a)
            aa["repo_id"] = repo_id
            aa["repo_hash"] = repo_hash
            merged.append(aa)

    def _key(a: dict[str, Any]) -> tuple[int, str, str, str, str]:
        t = str(a.get("type", ""))
        sr = _SEVERITY_RANK.get(t, 99)
        system_id = str(a.get("system_id", ""))
        repo_id = str(a.get("repo_id", ""))
        repo_hash = str(a.get("repo_hash", ""))
        return (sr, system_id, repo_id, repo_hash, t)

    merged.sort(key=_key)

    out: list[dict[str, Any]] = []
    for i, a in enumerate(merged, start=1):
        aa = dict(a)
        aa["priority"] = i
        out.append(aa)
    return out


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_bundle_meta(export_dir: Path, artifacts: list[str]) -> None:
    _write_json(export_dir / "bundle_meta.json", {"schema_version": "1.0", "artifacts": artifacts})


def _sorted_repo_results(repo_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def k(r: dict[str, Any]) -> tuple[str, str, str]:
        repo = r.get("repo") or {}
        return (str(repo.get("repo_id", "")), str(repo.get("repo_hash", "")), str(repo.get("repo_root", "")))

    return sorted(repo_results, key=k)


def _signals_nonzero(rr: dict[str, Any]) -> bool:
    gate = rr.get("gate") or {}
    if bool(gate.get("strict_failed", False)) or bool(gate.get("regression_detected", False)):
        return True
    return int(rr.get("exit_code", 0)) != 0


def run_portfolio_gate(
    *,
    repos: list[str] | None,
    repos_file: str | None,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: str | None,
    export_path: str | None,
    jobs: int,
    fail_fast: bool,
    max_repos: int | None,
    export_mode: str,
) -> tuple[dict[str, Any], int]:
    repo_paths: list[str] = []
    if repos_file:
        repo_paths.extend(_parse_repos_file(repos_file))
    if repos:
        repo_paths.extend(repos)
    if not repo_paths:
        payload = {
            "schema_version": PORTFOLIO_GATE_SCHEMA_VERSION,
            "command": "portfolio_gate",
            "error": "MISSING_REPOS",
            "hint": "portfolio-gate requires --repos and/or --repos-file",
        }
        return payload, 1

    if max_repos is not None:
        if int(max_repos) <= 0:
            payload = {
                "schema_version": PORTFOLIO_GATE_SCHEMA_VERSION,
                "command": "portfolio_gate",
                "error": "BAD_MAX_REPOS",
                "hint": "--max-repos must be >= 1",
            }
            return payload, 1
        repo_paths = repo_paths[: int(max_repos)]

    if export_mode not in {"portfolio-only", "with-repo-gates"}:
        payload = {
            "schema_version": PORTFOLIO_GATE_SCHEMA_VERSION,
            "command": "portfolio_gate",
            "error": "BAD_EXPORT_MODE",
            "hint": "--export-mode must be one of: portfolio-only, with-repo-gates",
        }
        return payload, 1

    jobs = int(jobs)
    if jobs < 1:
        payload = {
            "schema_version": PORTFOLIO_GATE_SCHEMA_VERSION,
            "command": "portfolio_gate",
            "error": "BAD_JOBS",
            "hint": "--jobs must be >= 1",
        }
        return payload, 1
    jobs = min(jobs, 16)

    specs = [_repo_spec(p) for p in repo_paths]
    specs.sort(key=lambda r: (r.repo_id, r.repo_hash, r.repo_root))

    repo_results: list[dict[str, Any]] = []

    if jobs == 1:
        for spec in specs:
            rr = _run_operator_gate_for_repo(
                spec,
                hide_samples=hide_samples,
                strict=strict,
                enforce_sla=enforce_sla,
                as_of=as_of,
            )
            repo_results.append(rr)
            if fail_fast and _signals_nonzero(rr):
                break
    elif not fail_fast:
        futures = []
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            for spec in specs:
                futures.append(
                    ex.submit(
                        _run_operator_gate_for_repo,
                        spec,
                        hide_samples=hide_samples,
                        strict=strict,
                        enforce_sla=enforce_sla,
                        as_of=as_of,
                    )
                )
            for fut in as_completed(futures):
                repo_results.append(fut.result())
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            pending = {}
            spec_index = 0

            while spec_index < len(specs) and len(pending) < jobs:
                spec = specs[spec_index]
                fut = ex.submit(
                    _run_operator_gate_for_repo,
                    spec,
                    hide_samples=hide_samples,
                    strict=strict,
                    enforce_sla=enforce_sla,
                    as_of=as_of,
                )
                pending[fut] = spec
                spec_index += 1

            stop_launching = False
            while pending:
                done, _ = wait(set(pending.keys()), return_when=FIRST_COMPLETED)
                for fut in done:
                    pending.pop(fut, None)
                    rr = fut.result()
                    repo_results.append(rr)
                    if _signals_nonzero(rr):
                        stop_launching = True

                while (not stop_launching) and spec_index < len(specs) and len(pending) < jobs:
                    spec = specs[spec_index]
                    fut = ex.submit(
                        _run_operator_gate_for_repo,
                        spec,
                        hide_samples=hide_samples,
                        strict=strict,
                        enforce_sla=enforce_sla,
                        as_of=as_of,
                    )
                    pending[fut] = spec
                    spec_index += 1

    repo_results = _sorted_repo_results(repo_results)
    top_actions = _merge_top_actions(repo_results)
    exit_code = _portfolio_exit_code(repo_results)

    payload: dict[str, Any] = {
        "schema_version": PORTFOLIO_GATE_SCHEMA_VERSION,
        "command": "portfolio_gate",
        "portfolio_exit_code": int(exit_code),
        "policy": {
            "hide_samples": bool(hide_samples),
            "strict": bool(strict),
            "enforce_sla": bool(enforce_sla),
            "as_of": as_of,
            "jobs": int(jobs),
            "fail_fast": bool(fail_fast),
            "max_repos": int(max_repos) if max_repos is not None else None,
            "export_mode": export_mode,
        },
        "repos": repo_results,
        "top_actions": top_actions,
        "artifacts": {"exported": bool(export_path)},
    }

    if export_path:
        export_dir = Path(export_path).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        _write_json(export_dir / "portfolio_gate.json", payload)

        artifacts: list[str] = ["bundle_meta.json", "portfolio_gate.json"]
        if export_mode == "with-repo-gates":
            for rr in repo_results:
                repo = rr.get("repo") or {}
                repo_hash = str(repo.get("repo_hash", "unknown"))
                fn = f"repo_{repo_hash}_operator_gate.json"
                gate_payload = rr.get("gate")
                if isinstance(gate_payload, dict):
                    _write_json(export_dir / fn, gate_payload)
                else:
                    _write_json(export_dir / fn, {})
                artifacts.append(fn)
            artifacts = sorted(set(artifacts))

        _write_bundle_meta(export_dir, artifacts)

    return payload, exit_code
