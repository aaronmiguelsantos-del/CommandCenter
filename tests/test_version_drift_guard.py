from __future__ import annotations

from scripts.version_drift_guard import evaluate_policy


def test_policy_blocks_marker_changes_without_metadata() -> None:
    status, errors = evaluate_policy(
        changed=["docs/CLI.md"],
        marker_changes=["v5.0.0"],
        version_errors=[],
    )
    assert status == "needs_attention"
    assert any("feature-level version markers changed" in item for item in errors)


def test_policy_passes_when_markers_and_metadata_change_together() -> None:
    status, errors = evaluate_policy(
        changed=["docs/CLI.md", "version.json", "docs/RELEASE_NOTES.md"],
        marker_changes=["v5.0.0"],
        version_errors=[],
    )
    assert status == "ok"
    assert not errors


def test_policy_blocks_partial_metadata_update() -> None:
    status, errors = evaluate_policy(
        changed=["version.json"],
        marker_changes=[],
        version_errors=[],
    )
    assert status == "needs_attention"
    assert any("version.json changed without docs/RELEASE_NOTES.md update" in item for item in errors)
