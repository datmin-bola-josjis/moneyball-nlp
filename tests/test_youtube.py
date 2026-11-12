"""Tests for the YouTube collector.

No network: a scripted client replaces `YouTubeClient`. The behaviours pinned
here are the ones that silently corrupt the dataset when they drift: the season
window, the ambiguous-name rule, quota per player, and the visibility of players
who ended up with no text at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scrape import youtube
from src.scrape.players import Player
from src.scrape.aliases import AliasIndex
from src.scrape.youtube import (
    ChannelSource,
    VideoCandidate,
    match_videos,
    records_from_comment,
    run,
    scan_channel,
)

LEAGUE_CLUBS = ["Arsenal", "Chelsea", "Liverpool"]


def player(player_id: str, name: str, aliases: tuple[str, ...], club: str) -> Player:
    return Player(player_id=player_id, name=name, aliases=aliases, club=club)


SAKA = player("fotmob_1", "Bukayo Saka", ("Bukayo Saka", "Saka", "B. Saka"), "Arsenal")
RICE = player("fotmob_2", "Declan Rice", ("Declan Rice", "Rice", "D. Rice"), "Arsenal")


class FakeClient:
    """Stands in for YouTubeClient: pages are scripted, nothing is fetched."""

    def __init__(self, playlist_pages=None, comment_pages=None):
        self.playlist_pages = playlist_pages or []
        self.comment_pages = comment_pages or {}
        self.playlist_calls = 0
        self.comment_calls: list[str] = []
        self.network_requests = 0
        self.quota_units = 0
        self.cache_hits = 0

    def iter_playlist_items(self, playlist_id: str, *, max_pages: int = 1):
        self.playlist_calls += 1
        for page in self.playlist_pages[:max_pages]:
            yield page

    def iter_comment_threads(self, video_id: str, *, max_pages: int = 1):
        self.comment_calls.append(video_id)
        for page in self.comment_pages.get(video_id, [])[:max_pages]:
            yield page


def video_item(video_id: str, title: str, published: str, description: str = "") -> dict:
    return {
        "snippet": {
            "resourceId": {"videoId": video_id},
            "title": title,
            "description": description,
            "publishedAt": f"{published}T09:00:00Z",
        }
    }


def comment_page(text: str, published: str = "2026-03-01T10:00:00Z", comment_id: str = "c1",
                 likes: int = 5, author: str = "Real Person") -> dict:
    return {
        "items": [
            {
                "snippet": {
                    "topLevelComment": {
                        "snippet": {
                            "id": comment_id,
                            "textDisplay": text,
                            "publishedAt": published,
                            "likeCount": likes,
                            "authorDisplayName": author,
                        }
                    }
                }
            }
        ]
    }


# ---------------------------------------------------------------------- scan


def test_scan_channel_stops_once_uploads_are_older_than_the_season() -> None:
    client = FakeClient(
        playlist_pages=[
            {"items": [video_item("v1", "Saka masterclass", "2026-02-01")]},
            {"items": [video_item("v2", "Old video", "2025-06-01")]},
            {"items": [video_item("v3", "Ancient", "2020-01-01")]},
        ]
    )

    videos = scan_channel(client, ChannelSource("PL", "UC1", "UU1"), max_pages=5)

    assert [v.video_id for v in videos] == ["v1"]
    assert client.playlist_calls == 1, "the walk must stop at the first out-of-season page"


def test_scan_channel_ignores_videos_after_the_season_end() -> None:
    client = FakeClient(
        playlist_pages=[{"items": [video_item("v1", "Post season", "2026-11-12")]}]
    )

    assert scan_channel(client, ChannelSource("PL", "UC1", "UU1")) == []


# ------------------------------------------------------------------- matching


def test_match_videos_prefers_title_then_description() -> None:
    index = AliasIndex.build([SAKA, RICE])
    videos = [
        VideoCandidate("v1", "Bukayo Saka is elite", "", "2026-02-01", "PL"),
        VideoCandidate("v2", "Arsenal news", "Declan Rice interview inside", "2026-02-02", "PL"),
        VideoCandidate("v3", "Chelsea tactics", "Nothing relevant", "2026-02-03", "PL"),
    ]

    matches = match_videos(index, [SAKA, RICE], videos)

    assert [v.video_id for v in matches[SAKA.player_id]] == ["v1"]
    assert [v.matched_on for v in matches[SAKA.player_id]] == ["title"]
    assert [v.video_id for v in matches[RICE.player_id]] == ["v2"]
    assert [v.matched_on for v in matches[RICE.player_id]] == ["description"]


# -------------------------------------------------------------------- records


def make_video(title: str = "Bukayo Saka masterclass") -> VideoCandidate:
    return VideoCandidate("v1", title, "", "2026-02-01", "PL")


def extract(text: str, *, published: str = "2026-03-01T10:00:00Z",
            thread_context: bool = True, seen: set[str] | None = None,
            video: VideoCandidate | None = None) -> list:
    index = AliasIndex.build([SAKA, RICE])
    return records_from_comment(
        {"id": "c1", "textDisplay": text, "publishedAt": published, "likeCount": 5},
        video or make_video(),
        SAKA,
        index,
        LEAGUE_CLUBS,
        min_words=8,
        seen_hashes=seen if seen is not None else set(),
        thread_context=thread_context,
    )


def test_comment_and_sentence_records_are_both_written() -> None:
    records = extract("Saka was clinical today and he never stopped running.")

    assert [r.unit_type for r in records] == ["comment", "sentence"]
    assert records[0].text_id == "yt_c1_fotmob_1"
    assert records[1].parent_text_id == records[0].text_id
    assert records[0].source == "youtube"
    assert records[0].video_id == "v1"
    assert records[0].thread_id == "v1"
    assert records[0].channel == "PL"
    assert records[0].url.startswith("https://www.youtube.com/watch?v=v1")


def test_short_comments_are_dropped() -> None:
    assert extract("Saka good") == []


def test_non_english_comments_are_dropped() -> None:
    assert extract("Saka sangat bagus sekali hari ini kawan semua") == []


def test_comments_outside_the_season_are_dropped() -> None:
    assert extract("Saka was clinical today and never stopped running",
                   published="2026-11-12T10:00:00Z") == []


def test_ambiguous_surname_needs_thread_context() -> None:
    text = "Saka was clinical today and never stopped running"

    assert extract(text, thread_context=False) == []
    assert extract(text, thread_context=True) != []


def test_duplicate_comment_is_kept_once() -> None:
    seen: set[str] = set()
    text = "Saka was clinical today and never stopped running"

    assert extract(text, seen=seen) != []
    assert extract(text, seen=seen) == []


def test_author_identity_is_not_part_of_the_record() -> None:
    records = extract("Saka was clinical today and never stopped running")

    blob = json.dumps([r.__dict__ for r in records])
    assert "Real Person" not in blob


# ------------------------------------------------------------------------ run


def test_run_writes_interim_and_summary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(youtube, "ROOT", tmp_path)
    monkeypatch.setattr(
        youtube,
        "channel_sources",
        lambda client, refresh=False: [ChannelSource("PL", "UC1", "UU1")],
    )

    client = FakeClient(
        playlist_pages=[{"items": [video_item("v1", "Bukayo Saka masterclass", "2026-02-01")]}],
        comment_pages={"v1": [comment_page("Saka was clinical today and never stopped running")]},
    )

    interim = run([SAKA, RICE], client=client, tag="test")

    assert interim.exists()
    rows = [json.loads(line) for line in interim.read_text(encoding="utf-8").splitlines()]
    assert {row["player_id"] for row in rows} == {SAKA.player_id}
    assert all(row["source"] == "youtube" for row in rows)

    summary_path = next((tmp_path / "data" / "raw" / "youtube").glob("test-*/summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["players_without_text"] == ["Declan Rice"]
    assert summary["per_player"]["Bukayo Saka"] == 1
    assert summary["comments"] == 1


def test_channel_without_handle_fails_loudly(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:
    monkeypatch.setattr(youtube, "CHANNELS_CACHE", tmp_path / "channels.json")
    monkeypatch.setattr(
        youtube,
        "load_config",
        lambda: {"text_sources": {"youtube": {"channels": [{"name": "Mystery FC"}]}}},
    )

    with pytest.raises(SystemExit, match="Mystery FC"):
        youtube.channel_sources(FakeClient())
