"""Tests for the cross-source dedupe.

The contract these pin is narrow on purpose. A naive `drop_duplicates` on
`text_clean_hash` would delete the sentence units the sentiment stage runs on and
break comments that legitimately mention two players, so most of these tests
exist to prove that it does *not* do that.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.link import dedupe


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def row(
    source: str,
    text: str,
    player_id: str = "fotmob_1",
    unit_type: str = "comment",
    digest: str | None = None,
    text_id: str | None = None,
    parent_text_id: str | None = None,
) -> dict:
    prefix = "rd" if source == "reddit" else "yt"
    stable = hashlib.sha1(
        f"{text}|{player_id}|{unit_type}|{parent_text_id}".encode("utf-8")
    ).hexdigest()[:10]
    record = {
        "text_id": text_id or f"{prefix}_{stable}",
        "player_id": player_id,
        "source": "reddit_arctic" if source == "reddit" else "youtube",
        "unit_type": unit_type,
        "text_raw": text,
        "text_clean": text,
        "text_clean_hash": digest if digest is not None else f"h_{text[:12]}",
        "language": "en",
        "created_at": "2026-03-01T00:00:00+00:00",
        "url": "https://example.invalid",
        "thread_id": "t1",
        "subreddit": "soccer" if source == "reddit" else "",
        "engagement": 1,
        "matched_alias": "Saka",
        "parent_text_id": parent_text_id,
    }
    # Real Reddit records do not carry these keys at all, so the fixture must not
    # either: the point of the output test is that missing keys become null.
    if source == "youtube":
        record["channel"] = "Sky Sports Premier League"
        record["video_id"] = "vid1"
    return record


def sentence_of(parent: dict, text: str, position: int = 0) -> dict:
    return row(
        "reddit" if parent["source"] == "reddit_arctic" else "youtube",
        text,
        player_id=parent["player_id"],
        unit_type="sentence",
        digest=f"h_{text[:12]}",
        text_id=f"{parent['text_id']}_s{position}",
        parent_text_id=parent["text_id"],
    )


# --------------------------------------------------------------------- merge


def test_identical_comment_is_dropped_from_youtube() -> None:
    text = "Saka was clinical today"
    reddit = [row("reddit", text)]
    youtube = [row("youtube", text)]

    rows, stats = dedupe.merge(reddit, youtube)

    assert [r["text_id"] for r in rows] == [reddit[0]["text_id"]]
    assert stats["dropped"]["comments"] == 1
    assert stats["kept"] == {"reddit": 1, "youtube": 0, "total": 1}


def test_same_text_for_two_players_is_kept() -> None:
    """One comment mentioning two players is two entity links, not a duplicate."""
    text = "Saka and Rice ran the midfield"
    reddit = [row("reddit", text, player_id="fotmob_1")]
    youtube = [row("youtube", text, player_id="fotmob_2")]

    rows, stats = dedupe.merge(reddit, youtube)

    assert len(rows) == 2
    assert stats["dropped"]["comments"] == 0


def test_comment_and_its_own_sentence_are_not_duplicates() -> None:
    text = "Saka was clinical"
    reddit = [row("reddit", text)]
    reddit.append(sentence_of(reddit[0], text))

    rows, stats = dedupe.merge(reddit, [])

    assert len(rows) == 2
    assert stats["dropped"]["sentences_same_text"] == 0


def test_sentences_of_a_dropped_comment_go_with_it() -> None:
    text = "Saka was clinical today"
    reddit = [row("reddit", text)]
    youtube_comment = row("youtube", text)
    youtube = [youtube_comment, sentence_of(youtube_comment, "Saka was clinical")]

    rows, stats = dedupe.merge(reddit, youtube)

    assert len(rows) == 1
    assert stats["dropped"]["comments"] == 1
    assert stats["dropped"]["sentences_parent_dropped"] == 1


def test_same_sentence_in_two_different_comments_is_dropped() -> None:
    """The same line quoted in two different comments is caught by pass three."""
    reddit_comment = row("reddit", "Saka was clinical, again")
    reddit = [reddit_comment, sentence_of(reddit_comment, "Saka was clinical")]
    youtube_comment = row("youtube", "unrelated words here about the match")
    youtube = [youtube_comment, sentence_of(youtube_comment, "Saka was clinical")]

    rows, stats = dedupe.merge(reddit, youtube)

    assert stats["dropped"]["comments"] == 0
    assert stats["dropped"]["sentences_same_text"] == 1
    assert [r["text_id"] for r in rows if r["unit_type"] == "sentence"] == [
        reddit[1]["text_id"]
    ]


def test_rows_without_a_hash_are_never_merged() -> None:
    reddit = [row("reddit", "Saka was clinical", digest="")]
    youtube = [row("youtube", "Saka was clinical", digest="")]

    rows, stats = dedupe.merge(reddit, youtube)

    assert len(rows) == 2
    assert stats["dropped"]["comments"] == 0


def test_identical_texts_within_one_source_are_counted_not_removed() -> None:
    """A duplicate the scraper missed is reported, because this pass cannot drop it."""
    reddit = [
        row("reddit", "Saka was clinical", text_id="rd_a"),
        row("reddit", "Saka was clinical", text_id="rd_b"),
    ]

    rows, stats = dedupe.merge(reddit, [])

    assert len(rows) == 2
    assert stats["diagnostics"]["reddit"]["within_player_repeats"] == 1


# ------------------------------------------------------------------ reading


def test_tag_selects_the_named_file_not_the_newest(tmp_path: Path) -> None:
    write_jsonl(
        tmp_path / "texts_reddit_full.jsonl",
        [row("reddit", "old run"), row("reddit", "old run two")],
    )
    write_jsonl(tmp_path / "texts_reddit_partial26.jsonl", [row("reddit", "pilot")])

    rows, path = dedupe.read_texts("reddit", "partial26", tmp_path)

    assert path.name == "texts_reddit_partial26.jsonl"
    assert len(rows) == 1


def test_missing_file_names_the_command_to_run(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="make scrape-arctic"):
        dedupe.read_texts("reddit", "full", tmp_path)


# ------------------------------------------------------------------- output


def test_output_keeps_every_column_and_nulls_youtube_only_fields(tmp_path: Path) -> None:
    reddit = [row("reddit", "Saka was clinical")]
    youtube = [row("youtube", "Saka is elite")]
    rows, _ = dedupe.merge(reddit, youtube)

    target = dedupe.write_output(rows, tmp_path / "out.parquet")
    frame = pd.read_parquet(target)

    assert list(frame.columns) == dedupe.COLUMNS
    assert len(frame) == 2
    assert frame.loc[frame["source"] == "reddit_arctic", "channel"].isna().all()
    assert frame.loc[frame["source"] == "youtube", "channel"].eq("Sky Sports Premier League").all()


def test_run_writes_output_and_report_without_touching_inputs(tmp_path: Path) -> None:
    reddit_file = write_jsonl(tmp_path / "texts_reddit_full.jsonl", [row("reddit", "Saka was clinical")])
    youtube_file = write_jsonl(tmp_path / "texts_youtube_full.jsonl", [row("youtube", "Saka was clinical")])
    before = (reddit_file.read_bytes(), youtube_file.read_bytes())

    out, report, stats = dedupe.run(
        interim=tmp_path,
        out=tmp_path / "texts_deduped.parquet",
        report=tmp_path / "dedupe.md",
    )

    assert out.exists() and report.exists()
    assert stats["dropped"]["comments"] == 1
    assert (reddit_file.read_bytes(), youtube_file.read_bytes()) == before


def test_an_unknown_column_is_reported_not_silently_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A handoff file with a new column must not lose it without a word."""
    extra = {**row("youtube", "Saka is elite"), "new_field_from_b": "x"}

    dedupe.write_output([extra], tmp_path / "out.parquet")

    assert "new_field_from_b" in caplog.text


# ------------------------------------------------------------------- report


def test_report_names_the_input_files_and_the_counts(tmp_path: Path) -> None:
    reddit = [row("reddit", "Saka was clinical")]
    youtube = [row("youtube", "Saka was clinical")]
    rows, stats = dedupe.merge(reddit, youtube)

    path = dedupe.write_report(
        stats, "texts_reddit_full.jsonl", "texts_youtube_full.jsonl", tmp_path / "dedupe.md"
    )
    text = path.read_text(encoding="utf-8")

    assert "texts_reddit_full.jsonl" in text
    assert "texts_youtube_full.jsonl" in text
    assert "| Komentar YouTube yang teksnya sama dengan Reddit | 1 |" in text


def test_zero_duplicates_is_reported_as_a_finding(tmp_path: Path) -> None:
    rows, stats = dedupe.merge([row("reddit", "Saka was clinical")], [row("youtube", "Saka is elite")])

    path = dedupe.write_report(
        stats, "texts_reddit_full.jsonl", "texts_youtube_full.jsonl", tmp_path / "dedupe.md"
    )
    text = path.read_text(encoding="utf-8")

    assert "Tidak ada duplikat silang yang ditemukan" in text
    assert "bukan" in text and "kegagalan" in text


def test_report_states_the_scope_rules_so_a_widened_rule_is_visible(tmp_path: Path) -> None:
    _, stats = dedupe.merge([row("reddit", "Saka was clinical")], [])

    path = dedupe.write_report(stats, "a.jsonl", "b.jsonl", tmp_path / "dedupe.md")
    text = path.read_text(encoding="utf-8")

    assert "untuk pemain yang sama" in text
    assert "Komentar dibandingkan dengan komentar" in text
    assert "Hanya antar sumber" in text
