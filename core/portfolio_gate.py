from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    if p.suffix.lower() == ".json":
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
    """
    Runs this engine's CLI against a repo's registry by:
    - setting cwd to repo_root (so relative globs/data resolution behave)
    - setting PYTHONPATH to engine root (so python -m app.main resolves)
    - passing --registry to the repo's registry json
    """
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
    root = _engine_root()
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    try:
        proc = subprocess.run(
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

    gate_payload: dict[str, Any] = {}
    stdout = (proc.stdout or "").strip()
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
        "exit_code": int(proc.returncode),
        "gate": _stable_gate_payload(gate_payload, int(proc.returncode)),
        "stderr": (proc.stderr or "").strip(),
    }


def _portfolio_exit_code(repo_results: list[dict[str, Any]]) -> int:
    if any(int(r.get("exit_code", 1)) not in _VALID_GATE_EXIT_CODES for r in repo_results):
        return 1

    strict_failed_any = False
    regression_any = False
    for r in repo_results:
        gate = r.get("gate")
        if not isinstance(gate, dict):
            continue
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
    """
    Deterministic merge:
    - annotate each action with repo_id + repo_hash
    - sort by (severity_rank, system_id, repo_id, repo_hash, type)
    - reassign priority 1..N
    """
    merged: list[dict[str, Any]] = []
    for rr in repo_results:
        repo = rr.get("repo")
        if not isinstance(repo, dict):
            continue
        repo_id = str(repo.get("repo_id", ""))
        repo_hash = str(repo.get("repo_hash", ""))
        gate = rr.get("gate")
        if not isinstance(gate, dict):
            continue
        actions = gate.get("top_actions")
        if not isinstance(actions, list):
            continue
        for a in actions:
            if not isinstance(a, dict):
                continue
            aa = dict(a)
            aa["repo_id"] = repo_id
            aa["repo_hash"] = repo_hash
            merged.append(aa)

    merged.sort(
        key=lambda a: (
            int(_SEVERITY_RANK.get(str(a.get("type", "")), 99)),
            str(a.get("system_id", "")),
            str(a.get("repo_id", "")),
            str(a.get("repo_hash", "")),
            str(a.get("type", "")),
            json.dumps(a, sort_keys=True),
        )
    )
    for i, a in enumerate(merged, start=1):
        a["priority"] = i
    return merged


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_bundle_meta(export_dir: Path, artifacts: list[str]) -> None:
    _write_json(
        export_dir / "bundle_meta.json",
        {
            "schema_version": "1.0",
            "artifacts": artifacts,
        },
    )


def run_portfolio_gate(
    *,
    repos: list[str] | None,
    repos_file: str | None,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: str | None,
    export_path: str | None,
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

    specs = [_repo_spec(p) for p in repo_paths]
    specs.sort(key=lambda r: (r.repo_id, r.repo_hash, r.repo_root))

    repo_results = [
        _run_operator_gate_for_repo(
            spec,
            hide_samples=bool(hide_samples),
            strict=bool(strict),
            enforce_sla=bool(enforce_sla),
            as_of=as_of,
        )
        for spec in specs
    ]

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
        },
        "repos": repo_results,
        "top_actions": top_actions,
        "artifacts": {"exported": bool(export_path)},
    }

    if export_path:
        export_dir = Path(export_path).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        _write_json(export_dir / "portfolio_gate.json", payload)
        _write_bundle_meta(export_dir, ["bundle_meta.json", "portfolio_gate.json"])

    return payload, int(exit_code)
