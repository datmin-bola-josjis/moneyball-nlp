"""Tests for the source-aware relevance harness.

The contract these pin is that adding YouTube cannot change the Reddit gate:
same sheet name, same report name, same numbers. YouTube gets its own files so
one gate can never overwrite the other.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.scrape import relevance


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )


def comment(source: str, text: str, player_id: str = "fotmob_1", **extra) -> dict:
    return {
        "text_id": f"{source}-{text[:6]}",
        "player_id": player_id,
        "source": source,
        "unit_type": "comment",
        "text_clean": text,
        "created_at": "2026-03-01T00:00:00+00:00",
        "url": "https://example.invalid",
        **extra,
    }


# --------------------------------------------------------------------- paths


def test_reddit_paths_are_unchanged() -> None:
    assert relevance.review_csv() == relevance.REVIEW_CSV
    assert relevance.report_path() == relevance.REPORT
    assert relevance.REVIEW_CSV.name == "review_relevance.csv"
    assert relevance.REPORT.name == "retrieval_relevance.md"


def test_youtube_files_do_not_collide_with_reddit() -> None:
    assert relevance.review_csv("youtube") != relevance.REVIEW_CSV
    assert relevance.report_path("youtube") != relevance.REPORT
    assert "youtube" in relevance.review_csv("youtube").name
    assert "youtube" in relevance.report_path("youtube").name


# --------------------------------------------------------------------- texts


def test_texts_reads_both_sources_for_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relevance, "INTERIM", tmp_path)
    write_jsonl(tmp_path / "texts_reddit_full.jsonl", [comment("reddit", "Saka is great")])
    write_jsonl(tmp_path / "texts_youtube_full.jsonl", [comment("youtube", "Saka is elite")])

    rows = relevance._texts(source="all")

    assert {row["source"] for row in rows} == {"reddit", "youtube"}


def test_texts_keeps_only_comment_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relevance, "INTERIM", tmp_path)
    sentence = {**comment("youtube", "Saka is elite"), "unit_type": "sentence"}
    write_jsonl(tmp_path / "texts_youtube_full.jsonl", [comment("youtube", "Saka is elite"), sentence])

    rows = relevance._texts(source="youtube")

    assert [row["unit_type"] for row in rows] == ["comment"]


def test_missing_source_names_the_command_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relevance, "INTERIM", tmp_path)

    with pytest.raises(SystemExit, match="src.scrape.youtube"):
        relevance._texts(source="youtube")


# ------------------------------------------------------------------- scoring


def test_youtube_sheet_groups_by_channel_and_writes_its_own_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relevance, "INTERIM", tmp_path)
    monkeypatch.setattr(relevance, "ROOT", tmp_path)
    sheet = tmp_path / "review_relevance_youtube.csv"
    with sheet.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=relevance.FIELDS + ["channel"], extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerow(
            {**comment("youtube", "Saka is elite"), "channel": "Sky Sports Premier League", "relevant": "y"}
        )
        writer.writerow(
            {**comment("youtube", "Pickford is bad"), "channel": "Sky Sports Premier League", "relevant": "n"}
        )

    report, stats = relevance.score_review(source="youtube", min_labelled=2)

    text = report.read_text(encoding="utf-8")
    assert report == tmp_path / "reports" / "retrieval_relevance_youtube.md"
    assert "YouTube" in text
    assert "Per channel" in text
    assert "Sky Sports Premier League" in text
    assert stats["rate"] == 0.5
    assert stats["labelled"] == 2
