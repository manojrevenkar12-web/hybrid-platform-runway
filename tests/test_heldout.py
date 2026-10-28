"""A blind set's first run is pinned to the exact files it ran on and never rewritten."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runway.evaluate import ROOT, sha

FIRST_RUNS = sorted((ROOT / "reports" / "heldout").glob("*/first_run.json"))


@pytest.mark.parametrize("first", FIRST_RUNS, ids=lambda p: p.parent.name)
def test_first_run_matches_its_set(first: Path) -> None:
    pinned = json.loads(first.read_text())
    assert pinned["sha256"] == sha(ROOT / "heldout" / first.parent.name)
    assert pinned["status_at_first_run"] == "blind"
