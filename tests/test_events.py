from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.events import last_event_ts_from_glob, parse_iso_utc


def test_parse_iso_utc_accepts_z_and_offsets() -> None:
    a = parse_iso_utc("2026-01-01T00:00:00Z")
    b = parse_iso_utc("2026-01-01T00:00:00+00:00")
    c = parse_iso_utc("2026-01-01T05:00:00+05:00")

    assert a is not None and a.tzinfo is not None
    assert b is not None and b.tzinfo is not None
    assert c is not None and c.tzinfo is not None

    assert a == b
    assert c == a


def test_last_event_ts_from_glob_ignores_bad_lines_and_picks_max(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    logs = tmp_path / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    (logs / "sys-events-a.jsonl").write_text(
        "\n".join(
            [
                "{not-json}",
                json.dumps({"type": "x"}),
                json.dumps({"ts": "2026-01-01T00:00:00Z", "type": "ok"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (logs / "sys-events-b.jsonl").write_text(
        json.dumps({"ts": "2026-01-03T12:00:00Z", "type": "ok"}) + "\n",
        encoding="utf-8",
    )

    dt = last_event_ts_from_glob("data/logs/sys-events-*.jsonl")
    assert dt is not None
    assert dt == datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc)


def test_last_event_ts_from_glob_returns_none_when_no_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    dt = last_event_ts_from_glob("data/logs/does-not-exist-*.jsonl")
    assert dt is None
