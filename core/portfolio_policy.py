from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PORTFOLIO_REPOS_MAP_SCHEMA_V1 = "1.0"
PORTFOLIO_REPOS_MAP_SCHEMA_V2 = "1.1"
SUPPORTED_PORTFOLIO_REPOS_MAP_SCHEMAS = (
    PORTFOLIO_REPOS_MAP_SCHEMA_V1,
    PORTFOLIO_REPOS_MAP_SCHEMA_V2,
)
DEFAULT_REPOS_MAP_PATH = "data/portfolio/repos.json"

_ALLOWED_ENTRY_KEYS = {
    "repo_id",
    "path",
    "owner",
    "required",
    "notes",
    "policy_overrides",
    "lifecycle",
    "group_key",
    "group_role",
    "execution_policy",
    "excluded_tasks",
    "task_timeouts_seconds",
}
_ALLOWED_POLICY_OVERRIDE_KEYS = {"strict", "enforce_sla", "hide_samples"}
_ALLOWED_EXECUTION_POLICY_KEYS = {
    "health_command",
    "release_command",
    "registry_command",
    "preferred_python",
}
_ALLOWED_TASKS = {"health", "release", "registry"}
_ALLOWED_LIFECYCLES = {"active", "archival", "experimental"}
_ALLOWED_GROUP_ROLES = {"primary", "clone", "backup"}


@dataclass(frozen=True)
class ExecutionPolicy:
    health_command: str = ""
    release_command: str = ""
    registry_command: str = ""
    preferred_python: str = ""

    def command_for_task(self, task: str) -> str:
        if task == "health":
            return self.health_command
        if task == "release":
            return self.release_command
        if task == "registry":
            return self.registry_command
        raise ValueError(f"unsupported task: {task}")


@dataclass(frozen=True)
class PortfolioRepo:
    repo_id: str
    repo_root: str
    owner: str
    required: bool
    notes: str
    policy_overrides: dict[str, bool]
    lifecycle: str
    group_key: str
    group_role: str
    execution_policy: ExecutionPolicy
    excluded_tasks: tuple[str, ...]
    task_timeouts_seconds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_root": self.repo_root,
            "owner": self.owner,
            "required": self.required,
            "notes": self.notes,
            "policy_overrides": dict(self.policy_overrides),
            "lifecycle": self.lifecycle,
            "group_key": self.group_key,
            "group_role": self.group_role,
            "execution_policy": {
                "health_command": self.execution_policy.health_command,
                "release_command": self.execution_policy.release_command,
                "registry_command": self.execution_policy.registry_command,
                "preferred_python": self.execution_policy.preferred_python,
            },
            "excluded_tasks": list(self.excluded_tasks),
            "task_timeouts_seconds": dict(self.task_timeouts_seconds),
        }


def _normalize_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"repos-map invalid: {field} must be a non-empty string")
    return value.strip()


def _validate_policy_overrides(raw: Any) -> dict[str, bool]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("repos-map invalid: policy_overrides must be an object")
    bad = set(raw.keys()) - _ALLOWED_POLICY_OVERRIDE_KEYS
    if bad:
        raise ValueError(f"repos-map invalid: unknown policy_overrides keys: {sorted(bad)}")
    return {str(k): bool(v) for k, v in raw.items()}


def _validate_execution_policy(raw: Any, repo_root: str) -> ExecutionPolicy:
    if raw is None:
        return ExecutionPolicy()
    if not isinstance(raw, dict):
        raise ValueError("repos-map invalid: execution_policy must be an object")
    bad = set(raw.keys()) - _ALLOWED_EXECUTION_POLICY_KEYS
    if bad:
        raise ValueError(f"repos-map invalid: unknown execution_policy keys: {sorted(bad)}")

    def _command(key: str) -> str:
        value = raw.get(key, "")
        if value == "":
            return ""
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"repos-map invalid: execution_policy.{key} must be a string")
        return value.strip()

    preferred_python = raw.get("preferred_python", "")
    if preferred_python:
        preferred_python = _require_nonempty_string(preferred_python, "execution_policy.preferred_python")
        if not Path(preferred_python).is_absolute():
            preferred_python = str((Path(repo_root) / preferred_python).resolve())

    return ExecutionPolicy(
        health_command=_command("health_command"),
        release_command=_command("release_command"),
        registry_command=_command("registry_command"),
        preferred_python=str(preferred_python),
    )


def _validate_excluded_tasks(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("repos-map invalid: excluded_tasks must be an array")
    tasks: list[str] = []
    for item in raw:
        task = _require_nonempty_string(item, "excluded_tasks[]")
        if task not in _ALLOWED_TASKS:
            raise ValueError(f"repos-map invalid: unknown excluded task: {task}")
        tasks.append(task)
    return tuple(sorted(set(tasks)))


def _validate_task_timeouts(raw: Any) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("repos-map invalid: task_timeouts_seconds must be an object")
    out: dict[str, float] = {}
    for key, value in raw.items():
        if key not in _ALLOWED_TASKS:
            raise ValueError(f"repos-map invalid: unknown timeout task: {key}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) <= 0:
            raise ValueError(f"repos-map invalid: timeout for {key} must be a positive number")
        out[str(key)] = float(value)
    return out


def _entry_from_map(raw: dict[str, Any]) -> PortfolioRepo:
    bad = set(raw.keys()) - _ALLOWED_ENTRY_KEYS
    if bad:
        raise ValueError(f"repos-map invalid: unknown repo entry keys: {sorted(bad)}")

    repo_id = _require_nonempty_string(raw.get("repo_id"), "repo_id")
    repo_root = _normalize_path(_require_nonempty_string(raw.get("path"), "path"))
    owner = str(raw.get("owner", "")).strip()
    required = bool(raw.get("required", True))
    notes = str(raw.get("notes", "")).strip()
    lifecycle = str(raw.get("lifecycle", "active")).strip() or "active"
    if lifecycle not in _ALLOWED_LIFECYCLES:
        raise ValueError(f"repos-map invalid: lifecycle must be one of {sorted(_ALLOWED_LIFECYCLES)}")
    group_key = str(raw.get("group_key", "")).strip() or repo_id
    group_role = str(raw.get("group_role", "primary")).strip() or "primary"
    if group_role not in _ALLOWED_GROUP_ROLES:
        raise ValueError(f"repos-map invalid: group_role must be one of {sorted(_ALLOWED_GROUP_ROLES)}")

    return PortfolioRepo(
        repo_id=repo_id,
        repo_root=repo_root,
        owner=owner,
        required=required,
        notes=notes,
        policy_overrides=_validate_policy_overrides(raw.get("policy_overrides")),
        lifecycle=lifecycle,
        group_key=group_key,
        group_role=group_role,
        execution_policy=_validate_execution_policy(raw.get("execution_policy"), repo_root=repo_root),
        excluded_tasks=_validate_excluded_tasks(raw.get("excluded_tasks")),
        task_timeouts_seconds=_validate_task_timeouts(raw.get("task_timeouts_seconds")),
    )


def _ad_hoc_repo(path_str: str) -> PortfolioRepo:
    repo_root = _normalize_path(path_str)
    repo_id = Path(repo_root).name or repo_root
    return PortfolioRepo(
        repo_id=repo_id,
        repo_root=repo_root,
        owner="",
        required=True,
        notes="ad_hoc_repo",
        policy_overrides={},
        lifecycle="active",
        group_key=repo_id,
        group_role="primary",
        execution_policy=ExecutionPolicy(),
        excluded_tasks=(),
        task_timeouts_seconds={},
    )


def default_repos_map_path() -> str | None:
    candidate = Path(DEFAULT_REPOS_MAP_PATH).expanduser().resolve()
    if candidate.exists():
        return str(candidate)
    return None


def load_portfolio_repos_map(path: str) -> list[PortfolioRepo]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"repos-map not found: {p}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repos-map invalid: top-level payload must be an object")
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version not in SUPPORTED_PORTFOLIO_REPOS_MAP_SCHEMAS:
        raise ValueError(
            f"repos-map schema_version drift: {schema_version} not in {list(SUPPORTED_PORTFOLIO_REPOS_MAP_SCHEMAS)}"
        )
    repos_raw = payload.get("repos")
    if not isinstance(repos_raw, list):
        raise ValueError("repos-map invalid: expected top-level key 'repos' as list")

    repos = [_entry_from_map(item) for item in repos_raw if isinstance(item, dict)]
    repos.sort(key=lambda item: (item.repo_id, item.repo_root))
    return repos


def _parse_repos_file(path: str) -> list[str]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"repos-file not found: {p}")
    items: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


def resolve_portfolio_repos(
    *,
    repos: list[str] | None = None,
    repos_file: str | None = None,
    repos_map: str | None = None,
    max_repos: int | None = None,
) -> list[PortfolioRepo]:
    if repos_map:
        specs = load_portfolio_repos_map(repos_map)
    elif repos:
        specs = [_ad_hoc_repo(item) for item in repos]
    elif repos_file:
        specs = [_ad_hoc_repo(item) for item in _parse_repos_file(repos_file)]
    else:
        default_map = default_repos_map_path()
        if default_map:
            specs = load_portfolio_repos_map(default_map)
        else:
            raise ValueError("portfolio-run requires --repos, --repos-file, or --repos-map")

    if max_repos is not None and max_repos < len(specs):
        specs = specs[: max(0, int(max_repos))]

    seen: set[tuple[str, str]] = set()
    out: list[PortfolioRepo] = []
    for spec in specs:
        key = (spec.repo_id, spec.repo_root)
        if key in seen:
            raise ValueError(f"repos-map invalid: duplicate repo entry for repo_id={spec.repo_id} path={spec.repo_root}")
        seen.add(key)
        out.append(spec)
    return out
