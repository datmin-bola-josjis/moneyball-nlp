"""Tests for the YouTube client.

No network: a scripted session stands in for the API, the same way
`tests/test_arctic_shift_client.py` does it. The behaviours pinned here are the
ones that cost real quota or leak real data when they drift:

* a cache hit must spend zero quota
* author identity must never reach disk (AGENTS.md rule 11)
* errors that cannot heal must not be retried
* a cache filename must not grow with the query, or Windows path limits break
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scrape.youtube_client import (
    CommentsDisabled,
    QuotaExceeded,
    YouTubeClient,
    YouTubeError,
)


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.headers = headers or {}
        self.text = json.dumps(self._payload)[:200]

    def json(self) -> dict:
        return self._payload


class FakeSession:
    """Returns scripted responses in order and records every call."""

    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers or {}})
        if not self.responses:
            raise AssertionError("unexpected extra network request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backoff and pacing must not make the suite slow."""
    monkeypatch.setattr("src.scrape.youtube_client.time.sleep", lambda *_: None)


def make_client(tmp_path: Path, responses: list) -> tuple[YouTubeClient, FakeSession]:
    session = FakeSession(responses)
    client = YouTubeClient(
        cache_dir=tmp_path / "cache", api_key_value="test-key", session=session
    )
    return client, session


COMMENT_PAYLOAD = {
    "kind": "youtube#commentThreadListResponse",
    "items": [
        {
            "snippet": {
                "topLevelComment": {
                    "snippet": {
                        "authorDisplayName": "Real Person",
                        "authorChannelId": {"value": "UCsecret"},
                        "authorProfileImageUrl": "https://example.invalid/a.png",
                        "textDisplay": "Saka's finishing has been clinical",
                        "likeCount": 12,
                    }
                },
                "totalReplyCount": 0,
            }
        }
    ],
}


# ------------------------------------------------------------------ caching


def test_cache_hit_spends_no_quota(tmp_path: Path) -> None:
    client, session = make_client(tmp_path, [FakeResponse(200, {"items": []})])

    client.get("channels", part="snippet", forHandle="@a")
    client.get("channels", part="snippet", forHandle="@a")

    assert client.network_requests == 1
    assert client.quota_units == 1
    assert client.cache_hits == 1
    assert len(session.calls) == 1


def test_cache_key_ignores_the_api_key(tmp_path: Path) -> None:
    first = YouTubeClient(cache_dir=tmp_path / "cache", api_key_value="key-one")
    second = YouTubeClient(cache_dir=tmp_path / "cache", api_key_value="key-two")

    left = first._cache_path("channels", {"part": "snippet"})
    right = second._cache_path("channels", {"part": "snippet"})

    assert left == right, "rotating the API key must not orphan the cache"


def test_cache_filename_stays_short_for_long_queries(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, [])
    path = client._cache_path("videos", {"id": "x" * 200, "part": "snippet,statistics"})

    assert path.parent.name == "videos"
    assert len(path.name) == len("0" * 32) + len(".json")


# ------------------------------------------------------------- data hygiene


def test_author_identity_never_reaches_disk(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, [FakeResponse(200, COMMENT_PAYLOAD)])

    payload = client.get("commentThreads", videoId="abc", part="snippet")

    blob = json.dumps(payload)
    assert "Real Person" not in blob
    assert "UCsecret" not in blob
    assert "example.invalid" not in blob
    assert "Saka's finishing" in blob, "stripping identity must not damage the text"

    cached = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "cache").rglob("*.json"))
    assert "Real Person" not in cached, "raw cache must not keep commenter names"
    assert "UCsecret" not in cached


# ---------------------------------------------------------------- failures


def test_comments_disabled_is_reported_not_retried(tmp_path: Path) -> None:
    body = {"error": {"code": 403, "message": "disabled", "errors": [{"reason": "commentsDisabled"}]}}
    client, session = make_client(tmp_path, [FakeResponse(403, body)])

    with pytest.raises(CommentsDisabled):
        client.get("commentThreads", videoId="abc", part="snippet")

    assert len(session.calls) == 1


def test_quota_exceeded_stops_immediately(tmp_path: Path) -> None:
    body = {"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}}
    client, session = make_client(tmp_path, [FakeResponse(403, body)])

    with pytest.raises(QuotaExceeded) as excinfo:
        client.get("channels", part="snippet", forHandle="@a")

    assert len(session.calls) == 1
    assert "midnight" in str(excinfo.value).lower()


def test_invalid_key_fails_fast(tmp_path: Path) -> None:
    body = {"error": {"code": 400, "message": "bad key", "errors": [{"reason": "keyInvalid"}]}}
    client, session = make_client(tmp_path, [FakeResponse(400, body)])

    with pytest.raises(YouTubeError, match="keyInvalid"):
        client.get("channels", part="snippet", forHandle="@a")

    assert len(session.calls) == 1


def test_server_error_is_retried_then_cached(tmp_path: Path) -> None:
    client, session = make_client(
        tmp_path, [FakeResponse(503, {}), FakeResponse(200, {"items": [1]})]
    )

    payload = client.get("channels", part="snippet", forHandle="@a")

    assert payload == {"items": [1]}
    assert len(session.calls) == 2
    assert client.quota_units == 2
    assert client.cache_hits == 0


# --------------------------------------------------------------- pagination


def test_pagination_honours_max_pages(tmp_path: Path) -> None:
    first = FakeResponse(200, {"items": [1], "nextPageToken": "TOKEN"})
    second = FakeResponse(200, {"items": [2]})
    client, session = make_client(tmp_path, [first, second])

    pages = list(client.iter_playlist_items("UU1", max_pages=2))

    assert [p["items"] for p in pages] == [[1], [2]]
    assert session.calls[0]["params"].get("pageToken") is None
    assert session.calls[1]["params"]["pageToken"] == "TOKEN"


def test_single_page_stops_without_a_token(tmp_path: Path) -> None:
    client, session = make_client(tmp_path, [FakeResponse(200, {"items": []})])

    pages = list(client.iter_playlist_items("UU1", max_pages=5))

    assert len(pages) == 1
    assert len(session.calls) == 1


# ------------------------------------------------------------------- config


def test_min_interval_cannot_go_below_the_floor(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="AGENTS.md"):
        YouTubeClient(cache_dir=tmp_path / "cache", api_key_value="k", min_interval=0.2)


def test_request_exception_redacts_api_key_in_logs_and_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import requests

    secret = "AIzaSyFakeTestSecretKey12345"
    err = requests.ConnectionError(
        f"Max retries exceeded with url: /youtube/v3/channels?part=snippet&key={secret}"
    )
    session = FakeSession([err] * 4)
    client = YouTubeClient(
        cache_dir=tmp_path / "cache", api_key_value=secret, session=session
    )

    with caplog.at_level("WARNING"):
        with pytest.raises(YouTubeError) as excinfo:
            client.get("channels", part="snippet")

    assert secret not in str(excinfo.value)
    assert secret not in caplog.text
    assert "<REDACTED>" in str(excinfo.value)
