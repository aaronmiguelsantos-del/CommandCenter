from __future__ import annotations

from ui.cli_cmds import SnapshotFlags, build_report_snapshot_diff_cmd, build_report_snapshot_stats_cmd, build_report_snapshot_tail_cmd


def test_snapshot_tail_cmd_includes_ledger_tail_and_no_strict_by_default() -> None:
    flags = SnapshotFlags(ledger="data/snapshots/report_snapshot_history.jsonl", tail=2000, strict=False)
    cmd = build_report_snapshot_tail_cmd(flags, n=20, registry="data/registry/systems.json", cli_python=".venv/bin/python")
    assert cmd[:3] == [".venv/bin/python", "-m", "app.main"]
    assert cmd[3:5] == ["report", "snapshot"]
    assert "--tail" in cmd
    assert "--ledger" in cmd
    assert "data/snapshots/report_snapshot_history.jsonl" in cmd
    assert "--strict" not in cmd
    assert "--enforce-sla" not in cmd
    assert "--include-staging" not in cmd
    assert "--include-dev" not in cmd


def test_snapshot_stats_cmd_includes_strict_flags_only_when_strict_enabled() -> None:
    flags = SnapshotFlags(
        ledger="data/snapshots/report_snapshot_history.jsonl",
        tail=1500,
        days=7,
        strict=True,
        enforce_sla=True,
        include_staging=True,
        include_dev=True,
    )
    cmd = build_report_snapshot_stats_cmd(flags, registry="/tmp/r.json", cli_python=".venv/bin/python")
    assert "--tail" in cmd
    assert "--ledger" in cmd
    assert "--strict" in cmd
    assert "--enforce-sla" in cmd
    assert "--include-staging" in cmd
    assert "--include-dev" in cmd
    assert "--registry" in cmd
    assert "/tmp/r.json" in cmd


def test_snapshot_diff_cmd_includes_ledger_tail_and_refs() -> None:
    flags = SnapshotFlags(ledger="data/snapshots/report_snapshot_history.jsonl", tail=999, strict=False)
    cmd = build_report_snapshot_diff_cmd(flags, a="prev", b="latest", cli_python=".venv/bin/python")
    assert "--ledger" in cmd
    assert "data/snapshots/report_snapshot_history.jsonl" in cmd
    assert "--tail" in cmd
    assert "999" in cmd
    assert "--a" in cmd and "prev" in cmd
    assert "--b" in cmd and "latest" in cmd
    assert "--strict" not in cmd


def test_snapshot_diff_cmd_can_include_as_of() -> None:
    flags = SnapshotFlags(ledger="data/snapshots/report_snapshot_history.jsonl", tail=999, strict=False)
    cmd = build_report_snapshot_diff_cmd(
        flags,
        a="prev",
        b="latest",
        as_of="2026-02-16T12:00:00Z",
        cli_python=".venv/bin/python",
    )
    assert "--as-of" in cmd
    assert "2026-02-16T12:00:00Z" in cmd
