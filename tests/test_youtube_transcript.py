"""Tests for the YouTube transcript collector.

No network. `transcript_fetcher` is injected, which is the whole reason the
fetcher is a parameter: the real one calls YouTube and cannot appear in a test.

The two behaviours worth pinning are (1) a missing transcript is a counter, not
a crash - most videos in a channel will not have captions - and (2) a transcript
segment obeys the same rule 17 context discipline as a comment, because a
broadcast transcript says "Saka" constantly and only some of those are about
Arsenal's Bukayo Saka.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scrape import youtube
from src.scrape.aliases import AliasIndex
from src.scrape.players import Player
from src.scrape.youtube import (
    TranscriptUnavailable,
    VideoCandidate,
    records_from_transcript,
    segment_transcript,
)

LEAGUE_CLUBS = ["Arsenal", "Chelsea", "Liverpool"]


def player(player_id: str, name: str, aliases: tuple[str, ...], club: str) -> Player:
    return Player(player_id=player_id, name=name, aliases=aliases, club=club)


SAKA = player("fotmob_1", "Bukayo Saka", ("Bukayo Saka", "Saka", "B. Saka"), "Arsenal")

VIDEO = VideoCandidate(
    video_id="vid001",
    title="Arsenal vs Chelsea | Match Review",
    description="",
    published_at="2026-01-15T10:00:00Z",
    channel="Premier League",
)


# ------------------------------------------------------------------ segmentation
def test_segment_transcript_splits_into_word_windows() -> None:
    """Windows are cut over the joined word stream, not per caption line.

    A line boundary is an artifact of how the captions were published, not a
    sentence boundary, so cutting per line would leave ragged fragments.
    """
    lines = ["Saka was excellent today", "he ran the whole game"]

    segments = segment_transcript(lines, window=4)

    assert segments == [
        "Saka was excellent today",
        "he ran the whole",
        "game",
    ]
    assert " ".join(segments).split() == " ".join(lines).split()


def test_segment_transcript_joins_fragments_before_windowing() -> None:
    """Captions arrive as ~3-word fragments; sentiment on those is noise."""
    lines = ["Saka", "was", "excellent", "today"]

    segments = segment_transcript(lines, window=4)

    assert segments == ["Saka was excellent today"]


def test_segment_transcript_returns_no_segments_for_empty_input() -> None:
    assert segment_transcript([]) == []
    assert segment_transcript(["", "   "]) == []


@pytest.mark.parametrize("window", [0, -5])
def test_segment_window_is_clamped_so_the_loop_terminates(window: int) -> None:
    """A zero/negative window would make `range(0, n, 0)` raise or spin."""
    segments = segment_transcript(["one two three"], window=window)

    assert segments, "a clamped window must still produce output"
    assert " ".join(segments) == "one two three"


# ---------------------------------------------------------------------- records
def _index() -> AliasIndex:
    return AliasIndex.build([SAKA])


def test_transcript_segment_is_kept_when_video_names_the_club() -> None:
    text = "Bukayo Saka has been the best player on the pitch across this whole season"

    records = records_from_transcript(
        [text],
        VIDEO,
        SAKA,
        _index(),
        LEAGUE_CLUBS,
        min_words=5,
        seen_hashes=set(),
        thread_context=True,
    )

    assert len(records) == 1
    record = records[0]
    assert record.unit_type == "sentence", (
        "PRD §8 locks unit_type to comment/sentence and Stage D reads only "
        "`sentence`; a bespoke type would never be analysed"
    )
    assert record.source == "youtube"
    assert record.player_id == SAKA.player_id
    assert record.channel == "Premier League"
    assert record.video_id == VIDEO.video_id
    assert record.subreddit == ""


def test_bare_surname_without_thread_context_is_dropped() -> None:
    """Rule 17: "Saka" alone in a broadcast could be any Saka."""
    text = "Saka was clinical in front of goal again this weekend and it mattered"

    records = records_from_transcript(
        [text],
        VIDEO,
        SAKA,
        _index(),
        LEAGUE_CLUBS,
        min_words=5,
        seen_hashes=set(),
        thread_context=False,
        counters=(counters := {}),
    )

    assert records == []
    assert counters.get("dropped_transcript_name_not_resolved") == 1


def test_duplicate_transcript_segments_are_dropped() -> None:
    text = "Bukayo Saka has been outstanding for Arsenal throughout this whole season"
    seen: set[str] = set()

    first = records_from_transcript(
        [text], VIDEO, SAKA, _index(), LEAGUE_CLUBS, 5, seen, True
    )
    second = records_from_transcript(
        [text], VIDEO, SAKA, _index(), LEAGUE_CLUBS, 5, seen, True
    )

    assert len(first) == 1
    assert second == []
    assert len(seen) == 1


def test_transcript_outside_the_season_window_is_rejected() -> None:
    old = VideoCandidate(
        video_id="old",
        title="Arsenal vs Chelsea",
        description="",
        published_at="2019-05-01T10:00:00Z",
        channel="Premier League",
    )
    text = "Bukayo Saka has been the best player on the pitch across this whole season"

    records = records_from_transcript(
        [text], old, SAKA, _index(), LEAGUE_CLUBS, 5, set(), True, counters=(c := {})
    )

    assert records == []
    assert c.get("dropped_transcript_outside_season") == 1


def test_short_transcript_segment_is_rejected() -> None:
    records = records_from_transcript(
        ["Saka good"], VIDEO, SAKA, _index(), LEAGUE_CLUBS, 5, set(), True, counters=(c := {})
    )

    assert records == []
    assert c.get("dropped_transcript_too_short") == 1


# ------------------------------------------------------------------------ run loop
def test_transcript_unavailable_is_counted_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A video without captions is normal; it must not abort the player."""
    calls: list[str] = []

    def failing_fetcher(video_id: str) -> list[str]:
        calls.append(video_id)
        raise TranscriptUnavailable("transcripts_disabled")

    counters: dict[str, int] = {}
    client = _StubClient()
    monkeypatch.setattr(youtube, "MAX_COMMENT_PAGES", 1)

    records = youtube.extract_for_player(
        client,
        SAKA,
        [VIDEO],
        _index(),
        LEAGUE_CLUBS,
        quota=5,
        min_words=5,
        counters=counters,
        include_transcript=True,
        transcript_fetcher=failing_fetcher,
    )

    assert calls == [VIDEO.video_id]
    assert counters.get("transcript_transcripts_disabled") == 1
    assert not [r for r in records if r.unit_type == "transcript_segment"]


def test_include_transcript_false_never_calls_the_fetcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The config flag is the switch; off means zero fetches, not a silent try."""
    calls: list[str] = []

    def fetcher(video_id: str) -> list[str]:
        calls.append(video_id)
        return ["Bukayo Saka Arsenal player of the match performance today"]

    monkeypatch.setattr(youtube, "MAX_COMMENT_PAGES", 1)

    youtube.extract_for_player(
        _StubClient(),
        SAKA,
        [VIDEO],
        _index(),
        LEAGUE_CLUBS,
        quota=5,
        min_words=5,
        counters={},
        include_transcript=False,
        transcript_fetcher=fetcher,
    )

    assert calls == [], "transcript_fetcher must not be called when the flag is off"


def test_transcript_segments_are_returned_alongside_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fetcher(video_id: str) -> list[str]:
        return [
            "Bukayo Saka has been the standout performer for Arsenal in every"
            " single match this season and nobody else comes close"
        ]

    monkeypatch.setattr(youtube, "MAX_COMMENT_PAGES", 1)

    records = youtube.extract_for_player(
        _StubClient(),
        SAKA,
        [VIDEO],
        _index(),
        LEAGUE_CLUBS,
        quota=5,
        min_words=5,
        counters={},
        include_transcript=True,
        transcript_fetcher=fetcher,
    )

    kinds = {record.unit_type for record in records}
    assert "comment" in kinds
    assert "sentence" in kinds


class _StubClient:
    """Minimal client: one comment thread that names the player."""

    def iter_comment_threads(self, video_id: str, max_pages: int = 2):
        yield {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "c1",
                            "snippet": {
                                "textDisplay": "Bukayo Saka was superb for Arsenal today",
                                "publishedAt": "2026-01-15T12:00:00Z",
                                "likeCount": 4,
                            },
                        }
                    }
                }
            ]
        }


def test_transcript_unit_type_is_readable_by_stage_d() -> None:
    """Regression guard: Stage D selects `unit_type == "sentence"` only.

    An earlier version emitted `transcript_segment`, which PRD §8 does not list.
    The records were written and then silently never analysed, so transcript
    coverage was reported but never reached a score. This pins the contract that
    makes the collected data reachable.
    """
    text = "Bukayo Saka has been the best player on the pitch across this whole season"

    records = records_from_transcript(
        [text], VIDEO, SAKA, _index(), LEAGUE_CLUBS, 5, set(), True
    )

    assert records, "the fixture must produce at least one record"
    for record in records:
        assert record.unit_type == "sentence"
        assert record.source == "youtube"


def test_transcript_counters_record_what_was_actually_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The summary must count transcript sentences without a bespoke unit_type.

    Transcript and comment sentences share `unit_type="sentence"`, so the only
    reliable counter is the one incremented where the record is appended. A
    `unit_type`-based sum silently reports 0.
    """

    def fetcher(video_id: str) -> list[str]:
        return [
            "Bukayo Saka has been the standout performer for Arsenal in every"
            " single match this season and nobody else comes close"
        ]

    monkeypatch.setattr(youtube, "MAX_COMMENT_PAGES", 1)
    counters: dict[str, int] = {}

    records = youtube.extract_for_player(
        _StubClient(),
        SAKA,
        [VIDEO],
        _index(),
        LEAGUE_CLUBS,
        quota=5,
        min_words=5,
        counters=counters,
        include_transcript=True,
        transcript_fetcher=fetcher,
    )

    transcript_records = [r for r in records if r.unit_type == "sentence"
                          and "_t" in r.text_id]
    assert transcript_records, "fixture must produce transcript sentences"
    assert counters["transcript_sentences_kept"] == len(transcript_records)
    assert counters.get("transcript_videos") == 1
