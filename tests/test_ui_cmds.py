from __future__ import annotations

from ui.cli_cmds import PolicyFlags, build_health_all_cmd, build_report_health_cmd


def test_default_ui_policy_hides_samples_in_health_all() -> None:
    policy = PolicyFlags()  # hide_samples=True by default
    cmd = build_health_all_cmd(
        cli_python=".venv/bin/python",
        registry_path=None,
        policy=policy,
        as_json=True,
    )
    assert cmd[:3] == [".venv/bin/python", "-m", "app.main"]
    assert cmd[3:5] == ["health", "--all"]
    assert "--json" in cmd
    assert "--hide-samples" in cmd
    assert "--strict" not in cmd


def test_show_samples_toggle_removes_hide_samples_flag() -> None:
    policy = PolicyFlags(hide_samples=False)
    cmd = build_health_all_cmd(
        cli_python=".venv/bin/python",
        registry_path="data/registry/systems.json",
        policy=policy,
        as_json=True,
    )
    assert "--registry" in cmd
    assert "data/registry/systems.json" in cmd
    assert "--hide-samples" not in cmd


def test_strict_enforce_sla_parity_is_applied_to_report_health() -> None:
    policy = PolicyFlags(strict=True, enforce_sla=True, hide_samples=True)
    cmd = build_report_health_cmd(
        cli_python=".venv/bin/python",
        registry_path="/tmp/codex-kernel-failcase/data/registry/systems.json",
        policy=policy,
        days=7,
        tail=500,
        include_hints=True,
        as_json=True,
    )
    # must include strict + enforce-sla and keep the registry
    assert cmd[:3] == [".venv/bin/python", "-m", "app.main"]
    assert cmd[3:6] == ["report", "health", "--days"]
    assert "--registry" in cmd
    assert "/tmp/codex-kernel-failcase/data/registry/systems.json" in cmd
    assert "--strict" in cmd
    assert "--enforce-sla" in cmd
    # report health never takes --hide-samples; sample suppression there is table-side
    assert "--hide-samples" not in cmd


def test_strict_flags_do_not_leak_when_strict_false() -> None:
    policy = PolicyFlags(strict=False, enforce_sla=True, include_staging=True, include_dev=True)
    cmd = build_report_health_cmd(
        cli_python=".venv/bin/python",
        registry_path=None,
        policy=policy,
        as_json=True,
    )
    assert "--strict" not in cmd
    assert "--enforce-sla" not in cmd
    assert "--include-staging" not in cmd
    assert "--include-dev" not in cmd
