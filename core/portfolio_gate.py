from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, TypedDict


# Portfolio Gate Contract
PORTFOLIO_GATE_SCHEMA_VERSION = "1.0"
REPOS_MAP_SCHEMA_VERSION = "1.0"


class RepoMapEntry(TypedDict, total=False):
    repo_id: str
    path: str
    owner: str
    required: bool
    notes: str


@dataclass(frozen=True)
class RepoSpec:
    repo_id: str
    repo_hash: str
    repo_root: str
    registry_path: str
    owner: str
    required: bool
    notes: str


# Error codes (portfolio-level typed failures)
ERR_REPO_PATH_NOT_FOUND = "REPO_PATH_NOT_FOUND"
ERR_REGISTRY_NOT_FOUND = "REGISTRY_NOT_FOUND"
ERR_SUBPROCESS_FAILED = "SUBPROCESS_FAILED"
ERR_INVALID_JSON = "INVALID_JSON"


_SEVERITY_RANK = {
    "STRICT_REGRESSION": 1,
    "STATUS_REGRESSION": 2,
    "RISK_INCREASE": 3,
    "NEW_HIGH_VIOLATIONS": 4,
}


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


def _repo_hash(repo_root_abs: str) -> str:
    return _sha256(repo_root_abs)[:12]


def _repo_spec_from_path(path_str: str) -> RepoSpec:
    repo_root, registry = _infer_repo_root_and_registry(path_str)
    repo_root_abs = _normalize_path(repo_root)
    registry_abs = _normalize_path(registry)

    base = Path(repo_root_abs).name or repo_root_abs

    return RepoSpec(
        repo_id=base,
        repo_hash=_repo_hash(repo_root_abs),
        repo_root=repo_root_abs,
        registry_path=registry_abs,
        owner="",
        required=True,
        notes="",
    )


def _load_repos_map(path: str) -> list[RepoMapEntry]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"repos-map not found: {p}")

    payload = json.loads(p.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REPOS_MAP_SCHEMA_VERSION:
        raise SystemExit(
            f"repos-map schema_version drift: {payload.get('schema_version')} != {REPOS_MAP_SCHEMA_VERSION}"
        )

    repos = payload.get("repos")
    if not isinstance(repos, list):
        raise SystemExit("repos-map invalid: expected top-level key 'repos' as list")

    out: list[RepoMapEntry] = []
    for r in repos:
        if not isinstance(r, dict):
            continue
        entry: RepoMapEntry = {
            "repo_id": str(r.get("repo_id", "")).strip(),
            "path": str(r.get("path", "")).strip(),
            "owner": str(r.get("owner", "")).strip(),
            "required": bool(r.get("required", True)),
            "notes": str(r.get("notes", "")).strip(),
        }
        if not entry["repo_id"] or not entry["path"]:
            raise SystemExit("repos-map invalid: each repo must include repo_id and path")
        out.append(entry)
    return out


def _spec_from_map_entry(entry: RepoMapEntry) -> RepoSpec:
    repo_root, registry = _infer_repo_root_and_registry(entry["path"])
    repo_root_abs = _normalize_path(repo_root)
    registry_abs = _normalize_path(registry)

    return RepoSpec(
        repo_id=entry["repo_id"],
        repo_hash=_repo_hash(repo_root_abs),
        repo_root=repo_root_abs,
        registry_path=registry_abs,
        owner=entry.get("owner", "") or "",
        required=bool(entry.get("required", True)),
        notes=entry.get("notes", "") or "",
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


def _base_repo_result(spec: RepoSpec) -> dict[str, Any]:
    return {
        "repo": {
            "repo_id": spec.repo_id,
            "repo_hash": spec.repo_hash,
            "repo_root": spec.repo_root,
            "registry_path": spec.registry_path,
            "owner": spec.owner,
            "required": bool(spec.required),
            "notes": spec.notes,
        },
        "repo_status": "ok",
        "error_code": None,
        "error_message": None,
        "exit_code": 0,
        "gate": {},
        "stderr": "",
    }


def _error_repo_result(spec: RepoSpec, *, code: str, msg: str) -> dict[str, Any]:
    rr = _base_repo_result(spec)
    rr["repo_status"] = "error"
    rr["error_code"] = code
    rr["error_message"] = msg
    rr["exit_code"] = 1
    rr["gate"] = {}
    rr["stderr"] = ""
    return rr


def _run_operator_gate_for_repo(
    spec: RepoSpec,
    *,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: Optional[str],
) -> dict[str, Any]:
    # Preflight: repo root exists
    if not Path(spec.repo_root).exists():
        return _error_repo_result(
            spec,
            code=ERR_REPO_PATH_NOT_FOUND,
            msg=f"repo_root not found: {spec.repo_root}",
        )

    # Preflight: registry exists
    if not Path(spec.registry_path).exists():
        return _error_repo_result(
            spec,
            code=ERR_REGISTRY_NOT_FOUND,
            msg=f"registry not found: {spec.registry_path}",
        )

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
    except Exception as e:
        return _error_repo_result(spec, code=ERR_SUBPROCESS_FAILED, msg=str(e))

    stdout = (p.stdout or "").strip()
    stderr = (p.stderr or "").strip()

    gate_payload: dict[str, Any] = {}
    if stdout:
        try:
            decoded = json.loads(stdout)
            if isinstance(decoded, dict):
                gate_payload = decoded
        except json.JSONDecodeError as e:
            rr = _error_repo_result(spec, code=ERR_INVALID_JSON, msg=f"invalid json stdout: {e}")
            rr["exit_code"] = int(p.returncode)
            rr["stderr"] = stderr
            return rr

    rr = _base_repo_result(spec)
    rr["exit_code"] = int(p.returncode)
    rr["gate"] = _stable_gate_payload(gate_payload, int(p.returncode))
    rr["stderr"] = stderr
    return rr


def _sorted_repo_results(repo_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Deterministic output ordering (independent of parallel completion order)
    def k(r: dict[str, Any]) -> tuple[str, str, str]:
        repo = r.get("repo") or {}
        return (str(repo.get("repo_id", "")), str(repo.get("repo_hash", "")), str(repo.get("repo_root", "")))

    return sorted(repo_results, key=k)


def _portfolio_exit_code(
    repo_results: list[dict[str, Any]],
    *,
    allow_missing: bool,
) -> int:
    strict_failed_any = False
    regression_any = False

    # Missing required repos count as regression unless allow_missing
    for r in repo_results:
        repo = r.get("repo") or {}
        required = bool(repo.get("required", True))
        status = str(r.get("repo_status", "ok"))
        if required and status == "error" and not allow_missing:
            regression_any = True

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
        for a in (gate.get("top_actions") or []):
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
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True, indent=2))
        f.write("\n")


def _write_bundle_meta(export_dir: Path, artifacts: list[str]) -> None:
    _write_json(export_dir / "bundle_meta.json", {"schema_version": "1.0", "artifacts": artifacts})


def _signals_nonzero(rr: dict[str, Any], *, allow_missing: bool) -> bool:
    gate = rr.get("gate") or {}
    if bool(gate.get("strict_failed", False)) or bool(gate.get("regression_detected", False)):
        return True
    is_required_error = bool((rr.get("repo") or {}).get("required", True)) and str(rr.get("repo_status", "ok")) == "error"
    if is_required_error and not allow_missing:
        return True
    return False


def run_portfolio_gate(
    *,
    repos: Optional[list[str]],
    repos_file: Optional[str],
    repos_map: Optional[str],
    allow_missing: bool,
    hide_samples: bool,
    strict: bool,
    enforce_sla: bool,
    as_of: Optional[str],
    export_path: Optional[str],
    jobs: int,
    fail_fast: bool,
    max_repos: Optional[int],
    export_mode: str,
) -> tuple[dict[str, Any], int]:
    # Resolve repo list priority:
    # 1) --repos-map
    # 2) --repos / --repos-file
    # 3) default repos-map at data/portfolio/repos.json if present and no explicit repos provided
    repo_specs: list[RepoSpec] = []

    if repos_map:
        entries = _load_repos_map(repos_map)
        repo_specs = [_spec_from_map_entry(e) for e in entries]
    else:
        # default repos-map if present and no explicit repo args
        default_map = Path(_engine_root()) / "data" / "portfolio" / "repos.json"
        if (not repos) and (not repos_file) and default_map.exists():
            entries = _load_repos_map(str(default_map))
            repo_specs = [_spec_from_map_entry(e) for e in entries]
        else:
            repo_paths: list[str] = []
            if repos_file:
                repo_paths.extend(_parse_repos_file(repos_file))
            if repos:
                repo_paths.extend(repos)
            if not repo_paths:
                raise SystemExit("portfolio-gate requires --repos-map or --repos/--repos-file")
            repo_specs = [_repo_spec_from_path(p) for p in repo_paths]

    # Apply max_repos safety valve after expansion
    if max_repos is not None:
        if int(max_repos) <= 0:
            raise SystemExit("--max-repos must be >= 1")
        repo_specs = repo_specs[: int(max_repos)]

    if export_mode not in {"portfolio-only", "with-repo-gates"}:
        raise SystemExit("--export-mode must be one of: portfolio-only, with-repo-gates")

    # Deterministic spec ordering
    repo_specs.sort(key=lambda r: (r.repo_id, r.repo_hash, r.repo_root))

    # jobs safety
    jobs = int(jobs)
    if jobs < 1:
        raise SystemExit("--jobs must be >= 1")
    jobs = min(jobs, 16)  # hard cap

    repo_results: list[dict[str, Any]] = []

    def run_one(spec: RepoSpec) -> dict[str, Any]:
        return _run_operator_gate_for_repo(
            spec,
            hide_samples=hide_samples,
            strict=strict,
            enforce_sla=enforce_sla,
            as_of=as_of,
        )

    if jobs == 1:
        for spec in repo_specs:
            rr = run_one(spec)
            repo_results.append(rr)
            if fail_fast and _signals_nonzero(rr, allow_missing=bool(allow_missing)):
                break
    else:
        futures: list[Future[dict[str, Any]]] = []
        stop_launch = False
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            for spec in repo_specs:
                if stop_launch:
                    break
                fut = ex.submit(run_one, spec)
                futures.append(fut)

                if fail_fast and len(futures) >= jobs:
                    # Opportunistic: if any completed already implies non-zero, stop launching more
                    for f in futures:
                        if not f.done():
                            continue
                        rr = f.result()
                        if _signals_nonzero(rr, allow_missing=bool(allow_missing)):
                            stop_launch = True
                            break

            for fut in as_completed(futures):
                repo_results.append(fut.result())

    repo_results = _sorted_repo_results(repo_results)
    top_actions = _merge_top_actions(repo_results)
    exit_code = _portfolio_exit_code(repo_results, allow_missing=bool(allow_missing))

    payload: dict[str, Any] = {
        "schema_version": PORTFOLIO_GATE_SCHEMA_VERSION,
        "command": "portfolio_gate",
        "portfolio_exit_code": int(exit_code),
        "policy": {
            "allow_missing": bool(allow_missing),
            "hide_samples": bool(hide_samples),
            "strict": bool(strict),
            "enforce_sla": bool(enforce_sla),
            "as_of": as_of,
            "jobs": int(jobs),
            "fail_fast": bool(fail_fast),
            "max_repos": int(max_repos) if max_repos is not None else None,
            "export_mode": export_mode,
            "repos_map": repos_map,
        },
        "repos": repo_results,
        "top_actions": top_actions,
        "artifacts": {"exported": bool(export_path)},
    }

    if export_path:
        export_dir = Path(export_path).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)

        artifacts: list[str] = ["bundle_meta.json", "portfolio_gate.json"]
        _write_json(export_dir / "portfolio_gate.json", payload)

        if export_mode == "with-repo-gates":
            for rr in repo_results:
                repo_hash = str((rr.get("repo") or {}).get("repo_hash", ""))
                if not repo_hash:
                    continue
                fn = f"repo_{repo_hash}_operator_gate.json"
                _write_json(export_dir / fn, rr.get("gate") or {})
                artifacts.append(fn)
            artifacts = sorted(artifacts)

        _write_bundle_meta(export_dir, artifacts)

    return payload, exit_code
