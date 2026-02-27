from __future__ import annotations

import json
from pathlib import Path

from core.portfolio_policy import load_portfolio_repos_map


def test_load_portfolio_repos_map_v1_defaults() -> None:
    repo = load_portfolio_repos_map("data/portfolio/repos.json")[0]
    assert repo.repo_id == "bootstrapping-engine"
    assert repo.lifecycle == "active"
    assert repo.group_role == "primary"
    assert repo.execution_policy.health_command
    assert repo.execution_policy.release_command
    assert repo.execution_policy.registry_command
    assert Path(repo.execution_policy.preferred_python).is_absolute()
    assert Path(repo.execution_policy.preferred_python).name.startswith("python")


def test_load_portfolio_repos_map_accepts_v1_0_shape(tmp_path: Path) -> None:
    repos_map = tmp_path / "repos.json"
    repos_map.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "repos": [
                    {
                        "repo_id": "demo",
                        "path": str(tmp_path / "demo"),
                        "owner": "Aaron",
                        "required": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    repos = load_portfolio_repos_map(str(repos_map))
    assert len(repos) == 1
    repo = repos[0]
    assert repo.repo_id == "demo"
    assert repo.lifecycle == "active"
    assert repo.group_key == "demo"
    assert repo.execution_policy.health_command == ""
    assert repo.excluded_tasks == ()


def test_load_portfolio_repos_map_resolves_relative_preferred_python(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repos_map = tmp_path / "repos.json"
    repos_map.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "repos": [
                    {
                        "repo_id": "demo",
                        "path": str(repo_root),
                        "execution_policy": {
                            "health_command": "{python} -c \"print('ok')\"",
                            "preferred_python": ".venv/bin/python",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    repo = load_portfolio_repos_map(str(repos_map))[0]
    assert repo.execution_policy.preferred_python == str((repo_root / ".venv/bin/python").resolve())
