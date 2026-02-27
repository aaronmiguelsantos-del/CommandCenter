from __future__ import annotations

from pathlib import Path


def test_portfolio_policy_contract_doc_mentions_required_fields() -> None:
    doc = Path("docs/PORTFOLIO_POLICY_CONTRACT.md").read_text(encoding="utf-8")
    assert "Repos map schema version: `1.1`" in doc
    assert "`data/portfolio/repos.json`" in doc
    assert "`operator portfolio-run`" in doc
    assert "health_command" in doc
    assert "release_command" in doc
    assert "registry_command" in doc
    assert "preferred_python" in doc
    assert "excluded_tasks" in doc
    assert "task_timeouts_seconds" in doc
    assert "lifecycle" in doc
    assert "group_role" in doc
