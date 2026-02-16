#!/usr/bin/env python3
"""Unit tests for rollup sorting behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_rollup_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_rollup.py"
    spec = importlib.util.spec_from_file_location("generate_daily_rollup", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRoadmapSortTieBreak(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rollup = _load_rollup_module()

    def test_sort_key_tie_breaks_are_deterministic(self) -> None:
        events = [
            {"skill": "fail-more", "status": "failure", "duration_ms": 90},
            {"skill": "fail-more", "status": "failure", "duration_ms": 100},
            {"skill": "fail-more", "status": "failure", "duration_ms": 110},
            {"skill": "fail-less", "status": "failure", "duration_ms": 40},
            {"skill": "fail-less", "status": "failure", "duration_ms": 60},
            {"skill": "tie-fast", "status": "failure", "duration_ms": 10},
            {"skill": "tie-slow", "status": "failure", "duration_ms": 20},
            {"skill": "a-tie", "status": "failure", "duration_ms": 30},
            {"skill": "z-tie", "status": "failure", "duration_ms": 30},
            {"skill": "good", "status": "success", "duration_ms": 10},
        ]

        report = self.rollup.build_rollup(releases=[], events=events)

        self.assertEqual(
            report["roadmap_priority"],
            [
                "fail-more",
                "fail-less",
                "tie-fast",
                "tie-slow",
                "a-tie",
                "z-tie",
                "good",
            ],
        )

    def test_unknown_skills_with_equal_metrics_sort_alphabetically(self) -> None:
        events = [
            {"skill": "unknown-zeta", "status": "failure", "duration_ms": 100},
            {"skill": "unknown-alpha", "status": "failure", "duration_ms": 100},
            {"skill": "unknown-beta", "status": "failure", "duration_ms": 100},
        ]

        report = self.rollup.build_rollup(releases=[], events=events)

        self.assertEqual(
            report["roadmap_priority"],
            ["unknown-alpha", "unknown-beta", "unknown-zeta"],
        )


if __name__ == "__main__":
    unittest.main()
