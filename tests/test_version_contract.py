from __future__ import annotations

import json
from pathlib import Path
import re


def test_version_json_contract_and_docs_alignment() -> None:
    repo = Path(__file__).resolve().parents[1]
    payload = json.loads((repo / "version.json").read_text(encoding="utf-8"))

    assert payload.get("schema_version") == "1.0"
    version = str(payload.get("version", ""))
    release_tag = str(payload.get("release_tag", ""))
    assert re.match(r"^\d+\.\d+\.\d+$", version)
    assert release_tag == f"v{version}"
    assert payload.get("release_notes") == "docs/RELEASE_NOTES.md"

    readme = (repo / "README.md").read_text(encoding="utf-8")
    cli_doc = (repo / "docs" / "CLI.md").read_text(encoding="utf-8")
    notes = (repo / "docs" / "RELEASE_NOTES.md").read_text(encoding="utf-8")

    assert "version.json" in readme
    assert release_tag in readme
    assert "version.json" in cli_doc
    assert release_tag in cli_doc
    assert f"## {release_tag}" in notes
