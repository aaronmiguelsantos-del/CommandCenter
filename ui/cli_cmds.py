from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PolicyFlags:
    strict: bool = False
    enforce_sla: bool = False
    include_staging: bool = False
    include_dev: bool = False
    hide_samples: bool = True  # operator default in UI


@dataclass(frozen=True)
class SnapshotFlags:
    ledger: str
    tail: int = 2000
    days: int = 7
    strict: bool = False
    enforce_sla: bool = False
    include_staging: bool = False
    include_dev: bool = False


def _base_python(cli_python: str) -> List[str]:
    # Always call the CLI the same way from UI: venv python -m app.main ...
    return [cli_python, "-m", "app.main"]


def build_health_all_cmd(
    *,
    cli_python: str,
    registry_path: Optional[str],
    policy: PolicyFlags,
    as_of: Optional[str] = None,
    as_json: bool = True,
) -> List[str]:
    cmd = _base_python(cli_python) + ["health", "--all"]
    if as_json:
        cmd.append("--json")
    if registry_path:
        cmd += ["--registry", registry_path]

    # policy flags
    if policy.strict:
        cmd.append("--strict")
        if policy.include_staging:
            cmd.append("--include-staging")
        if policy.include_dev:
            cmd.append("--include-dev")
        if policy.enforce_sla:
            cmd.append("--enforce-sla")

    if policy.hide_samples:
        cmd.append("--hide-samples")
    if as_of:
        cmd += ["--as-of", as_of]

    return cmd


def build_report_health_cmd(
    *,
    cli_python: str,
    registry_path: Optional[str],
    policy: PolicyFlags,
    days: int = 30,
    tail: int = 2000,
    include_hints: bool = True,
    as_of: Optional[str] = None,
    as_json: bool = True,
) -> List[str]:
    cmd = _base_python(cli_python) + ["report", "health", "--days", str(days), "--tail", str(tail)]
    if as_json:
        cmd.append("--json")
    if registry_path:
        cmd += ["--registry", registry_path]

    if policy.strict:
        cmd.append("--strict")
        if policy.include_staging:
            cmd.append("--include-staging")
        if policy.include_dev:
            cmd.append("--include-dev")
        if policy.enforce_sla:
            cmd.append("--enforce-sla")

    if not include_hints:
        cmd.append("--no-hints")
    if as_of:
        cmd += ["--as-of", as_of]

    return cmd


def build_report_graph_cmd(
    *,
    cli_python: str,
    registry_path: Optional[str],
    as_json: bool = True,
) -> List[str]:
    cmd = _base_python(cli_python) + ["report", "graph"]
    if as_json:
        cmd.append("--json")
    if registry_path:
        # graph supports --registry (and alias --registry-path)
        cmd += ["--registry", registry_path]
    return cmd


def _snapshot_policy_args(flags: SnapshotFlags, registry: str | None) -> list[str]:
    args: list[str] = []
    if registry:
        args += ["--registry", registry]
    if flags.strict:
        args.append("--strict")
        if flags.enforce_sla:
            args.append("--enforce-sla")
        if flags.include_staging:
            args.append("--include-staging")
        if flags.include_dev:
            args.append("--include-dev")
    return args


def build_report_snapshot_tail_cmd(
    flags: SnapshotFlags,
    n: int,
    registry: str | None = None,
    *,
    cli_python: str = "python",
) -> list[str]:
    return (
        _base_python(cli_python)
        + ["report", "snapshot", "--tail", str(flags.tail)]
        + _snapshot_policy_args(flags, registry)
        + [
            "tail",
            "--json",
            "--ledger",
            flags.ledger,
            "--n",
            str(n),
        ]
    )


def build_report_snapshot_stats_cmd(
    flags: SnapshotFlags,
    registry: str | None = None,
    *,
    cli_python: str = "python",
) -> list[str]:
    return (
        _base_python(cli_python)
        + ["report", "snapshot", "--tail", str(flags.tail)]
        + _snapshot_policy_args(flags, registry)
        + [
            "stats",
            "--json",
            "--ledger",
            flags.ledger,
            "--days",
            str(flags.days),
        ]
    )


def build_report_snapshot_run_cmd(
    flags: SnapshotFlags,
    every: int,
    count: int,
    registry: str | None = None,
    *,
    cli_python: str = "python",
) -> list[str]:
    return (
        _base_python(cli_python)
        + ["report", "snapshot", "--tail", str(flags.tail)]
        + _snapshot_policy_args(flags, registry)
        + [
            "run",
            "--json",
            "--every",
            str(every),
            "--count",
            str(count),
        ]
    )


def build_report_snapshot_diff_cmd(
    flags: SnapshotFlags,
    a: str,
    b: str,
    registry: str | None = None,
    as_of: str | None = None,
    *,
    cli_python: str = "python",
) -> list[str]:
    cmd = (
        _base_python(cli_python)
        + ["report", "snapshot"]
        + _snapshot_policy_args(flags, registry)
        + [
            "diff",
            "--json",
            "--ledger",
            flags.ledger,
            "--tail",
            str(flags.tail),
            "--a",
            a,
            "--b",
            b,
        ]
    )
    if as_of:
        cmd += ["--as-of", as_of]
    return cmd
