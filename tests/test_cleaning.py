"""Tests for the cleaning table.

The table is a report of counters, so the tests pin two things: every filter the
code applies has a row, and a summary from before the counters existed fails with
an instruction instead of rendering zeros.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.scrape import cleaning


def summary(examined: int = 200, kept: int = 100) -> dict:
    return {
        "run": "full-1",
        "filters": {
            "comments_examined": examined,
            "comments_kept": kept,
            "sentences_kept": 55,
            "dropped": {
                "too_short": 5,
                "not_english": 2,
                "bot_like": 1,
                "no_date": 0,
                "outside_season": 3,
                "duplicate": 9,
                "name_not_resolved": 80,
                "sentence_not_resolved": 11,
            },
        },
    }


def test_every_comment_filter_has_a_row() -> None:
    text = cleaning.render(summary(), "full-1")

    for key, label, _ in cleaning.COMMENT_FILTERS:
        assert label in text, key
    assert "Kalimat yang lolos: **55**" in text


def test_filters_are_listed_in_the_order_they_run() -> None:
    text = cleaning.render(summary(), "full-1")

    positions = [text.index(label) for _, label, _ in cleaning.COMMENT_FILTERS]
    assert positions == sorted(positions)


def test_an_unaccounted_remainder_is_reported() -> None:
    """Comments skipped when the quota is reached mid-page must not vanish."""
    text = cleaning.render(summary(examined=210), "full-1")

    assert "**10**" in text


def test_zero_examined_does_not_divide_by_zero() -> None:
    text = cleaning.render(summary(examined=0, kept=0), "full-1")

    assert "—" in text


def test_a_new_filter_is_named_instead_of_explained_as_quota_truncation() -> None:
    """A counter added to the collector must not be read as 'skipped at quota'."""
    payload = summary()
    payload["filters"]["dropped"]["off_topic"] = 4

    text = cleaning.render(payload, "full-1")

    assert "Filter yang belum punya baris di tabel" in text
    assert "| `off_topic` | 4 |" in text


def test_the_current_run_has_no_unmapped_filters() -> None:
    text = cleaning.render(summary(), "full-1")

    assert "Filter yang belum punya baris di tabel" not in text


def test_a_summary_without_counters_names_the_fix(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"run": "old"}), encoding="utf-8")

    with pytest.raises(SystemExit, match="make scrape-youtube"):
        cleaning.load_summary(path)


def test_latest_summary_picks_the_newest_run(tmp_path: Path) -> None:
    old = tmp_path / "full-old"
    new = tmp_path / "full-new"
    old.mkdir()
    new.mkdir()
    for folder in (old, new):
        (folder / "summary.json").write_text(json.dumps({"filters": {}}), encoding="utf-8")
    os.utime(old / "summary.json", (1_700_000_000, 1_700_000_000))
    os.utime(new / "summary.json", (1_800_000_000, 1_800_000_000))

    assert cleaning.latest_summary(tmp_path) == new / "summary.json"


def test_run_writes_the_report(tmp_path: Path) -> None:
    folder = tmp_path / "full-1"
    folder.mkdir()
    (folder / "summary.json").write_text(json.dumps(summary()), encoding="utf-8")

    target = cleaning.run(folder, tmp_path / "cleaning.md")

    text = target.read_text(encoding="utf-8")
    assert "Tabel Cleaning YouTube" in text
    assert "`full-1`" in text
