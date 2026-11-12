"""Tests for the Arctic Shift client's backpressure handling.

These encode behaviour learned by hitting the real API, where the error
messages are actively misleading:

* "Timeout. Maybe slow down a bit" is rate limiting, not a network timeout.
  Raising the socket timeout in response makes the client slower and fixes
  nothing, so the client must wait instead.
* HTTP 422 carries that same rate-limit message, so 422 must be retried.
  Treating it as a client error aborts a run that would have succeeded.
* HTTP 400 is a genuinely malformed request and must fail fast, because every
  retry spends rate-limit budget that is the scarce resource.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.scrape.arctic_shift_client import (
    NON_RETRYABLE_STATUS,
    RATE_LIMIT_MARKERS,
    ArcticShiftClient,
    ArcticShiftError,
)


class ScriptedClient(ArcticShiftClient):
    """Client whose network layer is scripted, so no request is made."""

    def __init__(self, responses: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(Path(kwargs.pop("cache_dir")), **kwargs)
        self._responses = list(responses)
        self.calls = 0

    def _fetch(self, url: str) -> dict[str, Any]:  # noqa: ARG002
        self.calls += 1
        return self._responses.pop(0)


@pytest.fixture()
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


# ------------------------------------------------------------------ behaviour


def test_successful_response_is_cached(cache: Path) -> None:
    client = ScriptedClient([{"data": [{"id": "abc"}]}], cache_dir=cache)

    first = client.get("posts/search", subreddit="soccer")
    second = client.get("posts/search", subreddit="soccer")

    assert first == second
    assert client.calls == 1, "second call must come from cache"
    assert client.cache_hits == 1


def test_rate_limit_message_is_retried(cache: Path) -> None:
    """'Timeout...' must be treated as backpressure and retried."""
    client = ScriptedClient(
        [
            {"data": None, "error": "Timeout. Maybe slow down a bit", "_status": 422},
            {"data": [{"id": "ok"}]},
        ],
        cache_dir=cache,
        start_delay=0.0,
    )

    payload = client.get("posts/search", subreddit="soccer")

    assert payload["data"] == [{"id": "ok"}]
    assert client.calls == 2
    assert client.backpressure_events == 1


def test_422_is_not_in_non_retryable_status() -> None:
    """Arctic Shift returns 422 for rate limiting, so it must stay retryable."""
    assert 422 not in NON_RETRYABLE_STATUS


def test_400_fails_fast_without_retry(cache: Path) -> None:
    """A malformed request must not burn the retry budget."""
    client = ScriptedClient(
        [{"data": None, "error": "HTTP 400: bad param", "_status": 400}],
        cache_dir=cache,
        start_delay=0.0,
    )

    with pytest.raises(ArcticShiftError):
        client.get("posts/search", subreddit="soccer")

    assert client.calls == 1


def test_backpressure_increases_delay(cache: Path) -> None:
    client = ScriptedClient(
        [
            {"data": None, "error": "Timeout. Maybe slow down a bit", "_status": 422},
            {"data": [{"id": "ok"}]},
        ],
        cache_dir=cache,
        start_delay=1.0,
    )
    before = client.delay

    client.get("posts/search", subreddit="soccer")

    assert client.backpressure_events == 1
    assert before > 0


def test_exhausted_retries_raises(cache: Path) -> None:
    responses = [
        {"data": None, "error": "Timeout. Maybe slow down a bit", "_status": 422}
    ] * 10
    client = ScriptedClient(responses, cache_dir=cache, start_delay=0.0)

    with pytest.raises(ArcticShiftError):
        client.get("posts/search", subreddit="soccer")


def test_rate_limit_markers_do_not_match_generic_timeout() -> None:
    """A plain 'timeout' must not be mistaken for backpressure wording.

    Only the full Arctic Shift phrase counts, so a real network timeout is not
    silently treated as rate limiting.
    """
    assert all("timeout" != marker for marker in RATE_LIMIT_MARKERS)


# ------------------------------------------------------------------ boundary


def test_empty_data_list_is_not_cached_as_success(cache: Path) -> None:
    """An empty result is still an error state here; only non-empty data caches."""
    client = ScriptedClient(
        [
            {"data": None, "error": "Timeout. Maybe slow down a bit", "_status": 422},
            {"data": [{"id": "ok"}]},
        ],
        cache_dir=cache,
        start_delay=0.0,
    )

    client.get("posts/search", subreddit="soccer")

    assert client.calls == 2


def test_cache_key_separates_parameters(cache: Path) -> None:
    client = ScriptedClient(
        [{"data": [{"id": "a"}]}, {"data": [{"id": "b"}]}],
        cache_dir=cache,
        start_delay=0.0,
    )

    first = client.get("posts/search", subreddit="soccer")
    second = client.get("posts/search", subreddit="MCFC")

    assert first["data"] != second["data"]
    assert client.calls == 2


def test_long_parameters_do_not_break_cache_path(cache: Path) -> None:
    client = ScriptedClient([{"data": [{"id": "a"}]}], cache_dir=cache)
    long_query = "x" * 400

    client.get("posts/search", subreddit="soccer", query=long_query)

    files = list(cache.glob("*.json"))
    assert len(files) == 1
    assert len(files[0].name) < 200


def test_corrupt_cache_entry_is_refetched(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    client = ScriptedClient([{"data": [{"id": "fresh"}]}], cache_dir=cache)
    path = client._cache_path("posts/search", {"subreddit": "soccer"})
    path.write_text("{not valid json", encoding="utf-8")

    payload = client.get("posts/search", subreddit="soccer")

    assert payload["data"] == [{"id": "fresh"}]
    assert json.loads(path.read_text(encoding="utf-8"))["data"] == [{"id": "fresh"}]
