"""YouTube Data API v3 client: cached, throttled, retried, quota-aware.

Design constraints come from AGENTS.md and from what this API actually does:

  * at least one second between requests, never lower
  * retries with exponential backoff, but never on errors that cannot heal
  * every response is cached on disk before it is interpreted, so a run that
    dies halfway keeps the quota it already spent
  * comment payloads are stripped of author identity *before* they are cached:
    rule 11 forbids keeping commenter names or channel ids, and a raw cache
    would otherwise smuggle them onto disk
  * one unit of quota per call is counted, because 10,000 units/day is the real
    budget and `search.list` costs 100 of them

Two API facts that are easy to get wrong and are encoded here:

  * `commentsDisabled` arrives as HTTP 403 with that reason code. It is a
    property of the video, not a failure of the run, so it is raised as its own
    exception and the caller counts it instead of aborting.
  * `quotaExceeded` will not heal by retrying; it resets at midnight Pacific
    time. Retrying burns wall-clock for nothing, so it raises immediately.

Cache filenames are ``<endpoint>/<sha256[:32]>.json``. Short and fixed-length on
purpose: a filename built from query parameters grows with the query and breaks
the 260-character Windows path limit (see the Arctic Shift cache bug).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Final, Iterator

import requests

from src.config import ROOT, load_config, load_env

log = logging.getLogger("youtube")

BASE_URL: Final[str] = "https://www.googleapis.com/youtube/v3"
USER_AGENT: Final[str] = "moneyball-nlp/0.1 (academic project; contact via repository)"
DEFAULT_TIMEOUT: Final[int] = 30
MIN_INTERVAL: Final[float] = 1.0
MAX_ATTEMPTS: Final[int] = 4
BACKOFF_BASE: Final[float] = 2.0
MAX_RESULTS: Final[int] = 100

# Fields that identify a commenter. Removed recursively before the payload is
# cached or returned (AGENTS.md rule 11).
AUTHOR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "authorDisplayName",
        "authorChannelId",
        "authorChannelUrl",
        "authorProfileImageUrl",
        "authorGoogleplusProfileUrl",
    }
)

# Reasons that will never succeed on retry. Retrying them only spends quota.
HARD_REASONS: Final[frozenset[str]] = frozenset(
    {
        "keyInvalid",
        "accessNotConfigured",
        "forbidden",
        "ipRefererBlocked",
        "playlistNotFound",
        "videoNotFound",
        "badRequest",
    }
)

RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})


class YouTubeError(RuntimeError):
    """Raised when a YouTube request fails permanently."""


class QuotaExceeded(YouTubeError):
    """Daily quota is gone. Only waiting for the Pacific-time reset helps."""


class CommentsDisabled(YouTubeError):
    """The video has comments turned off; this is data, not a failure."""


def _redact_key(text: str, api_key_value: str) -> str:
    redacted = re.sub(r"([?&]key=)[^&\s\"']+", r"\1<REDACTED>", text)
    if api_key_value:
        redacted = redacted.replace(api_key_value, "<REDACTED>")
    return redacted


def _error_info(payload: dict[str, Any]) -> tuple[str, str]:
    error = payload.get("error") or {}
    errors = error.get("errors") or []
    reason = str(errors[0].get("reason", "")) if errors else ""
    return reason, str(error.get("message") or "")


def _strip_authors(node: Any) -> Any:
    """Remove author identity from a payload, in place, at any depth."""
    if isinstance(node, dict):
        for field in AUTHOR_FIELDS:
            node.pop(field, None)
        for value in node.values():
            _strip_authors(value)
    elif isinstance(node, list):
        for value in node:
            _strip_authors(value)
    return node


def api_key() -> str:
    """Read the key from `.env`; fail with the YouTube instructions, not Reddit's."""
    load_env()
    value = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not value:
        raise SystemExit(
            "missing YOUTUBE_API_KEY in .env.\n"
            "Google Cloud Console > APIs & Services > Library > enable "
            "'YouTube Data API v3' > Credentials > Create credentials > API key.\n"
            "See .env.example for the exact variable name."
        )
    return value


class YouTubeClient:
    """Calls the YouTube Data API with pacing, retries, and a disk cache.

    Parameters
    ----------
    cache_dir:
        Where responses are stored. A cache hit performs no network request and
        spends no quota.
    min_interval:
        Minimum seconds between network requests. Config may raise it, never
        lower it below one second.
    api_key:
        Overrides the key from `.env`; used by tests.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        min_interval: float | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        api_key_value: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        cfg = load_config()["text_sources"].get("youtube", {})
        configured = float(cfg.get("rate_limit_seconds", MIN_INTERVAL))
        if min_interval is not None and min_interval < MIN_INTERVAL:
            raise ValueError(
                f"min_interval must be >= {MIN_INTERVAL}s per AGENTS.md, got {min_interval}"
            )
        # Config may only raise the floor, never lower it.
        self.min_interval = max(MIN_INTERVAL, configured if min_interval is None else min_interval)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or ROOT / "data" / "raw" / "youtube" / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._key = api_key_value
        self._session = session or requests.Session()
        self._last_request_at = 0.0
        self.network_requests = 0
        self.cache_hits = 0
        self.quota_units = 0

    # ------------------------------------------------------------- internals

    def _key_value(self) -> str:
        if self._key is None:
            self._key = api_key()
        return self._key

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        digest = hashlib.sha256(
            json.dumps([endpoint, params], sort_keys=True).encode()
        ).hexdigest()[:32]
        return self.cache_dir / endpoint / f"{digest}.json"

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    # ------------------------------------------------------------------ public

    def get(self, endpoint: str, *, force: bool = False, **params: Any) -> dict[str, Any]:
        """Return parsed JSON for an endpoint, using the cache when present."""
        params = {key: value for key, value in params.items() if value is not None}
        cache_path = self._cache_path(endpoint, params)

        if cache_path.exists() and not force:
            try:
                self.cache_hits += 1
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warning("corrupt cache entry, refetching: %s", cache_path.name)

        query = dict(params)
        key_value = self._key_value()
        query["key"] = key_value
        url = f"{BASE_URL}/{endpoint}"

        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._throttle()
            self.network_requests += 1
            self.quota_units += 1  # every list/get call costs exactly one unit
            try:
                response = self._session.get(
                    url,
                    params=query,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                safe_exc = _redact_key(str(exc), key_value)
                last_error = f"network: {safe_exc}"
                log.warning("request failed (%d/%d) %s: %s", attempt, MAX_ATTEMPTS, endpoint, safe_exc)
            else:
                if response.status_code == 200:
                    payload = _strip_authors(response.json())
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(payload), encoding="utf-8")
                    return payload

                try:
                    body = response.json()
                except ValueError:
                    body = {}
                reason, message = _error_info(body)
                safe_message = _redact_key(message[:200], key_value)
                safe_body = _redact_key(response.text[:200], key_value)

                if reason == "commentsDisabled":
                    raise CommentsDisabled(f"comments disabled on {params}")
                if reason in {"quotaExceeded", "dailyLimitExceeded"}:
                    raise QuotaExceeded(
                        f"daily quota exhausted ({reason}). It resets at midnight "
                        "Pacific time; rerun then. The cache keeps what was already fetched."
                    )
                if reason in HARD_REASONS:
                    raise YouTubeError(
                        f"HTTP {response.status_code} {reason}: {safe_message}"
                    )

                last_error = f"HTTP {response.status_code} {reason or 'unknown'}"
                if response.status_code not in RETRYABLE_STATUS and reason != "rateLimitExceeded":
                    raise YouTubeError(
                        f"HTTP {response.status_code} for {endpoint} {params}: "
                        f"{safe_message or safe_body}"
                    )
                retry_after = response.headers.get("Retry-After")
                delay = min(float(retry_after), 60.0) if retry_after else BACKOFF_BASE**attempt
                log.warning(
                    "backing off %.1fs (%d/%d) %s: %s", delay, attempt, MAX_ATTEMPTS, endpoint, last_error
                )
                time.sleep(delay)
                continue

            if attempt < MAX_ATTEMPTS:
                delay = BACKOFF_BASE**attempt
                log.info("backing off %.1fs", delay)
                time.sleep(delay)

        raise YouTubeError(f"exhausted {MAX_ATTEMPTS} attempts on {endpoint}: {last_error}")

    # --------------------------------------------------------------- endpoints

    def channel_by_handle(self, handle: str) -> dict[str, Any] | None:
        """Resolve `@handle` to a channel item, or None when the handle is unused.

        The caller must check the returned title: a wrong handle often resolves
        to a fan channel rather than failing (verified 2026-11-12: @SkySportsPL
        is 'TRS SkySports', not Sky Sports).
        """
        payload = self.get("channels", part="snippet,contentDetails", forHandle=handle)
        items = payload.get("items") or []
        return items[0] if items else None

    def iter_playlist_items(
        self, playlist_id: str, *, max_pages: int = 1
    ) -> Iterator[dict[str, Any]]:
        """Yield pages of an uploads playlist, bounded by `max_pages`."""
        return self._paginate(
            "playlistItems",
            {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50},
            max_pages=max_pages,
        )

    def iter_comment_threads(
        self, video_id: str, *, max_pages: int = 1
    ) -> Iterator[dict[str, Any]]:
        """Yield pages of top-level comment threads for one video.

        Raises `CommentsDisabled` on the first page when the video has them off.
        """
        return self._paginate(
            "commentThreads",
            {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": MAX_RESULTS,
                "textFormat": "plainText",
                "order": "relevance",
            },
            max_pages=max_pages,
        )

    def videos(self, video_ids: list[str]) -> dict[str, Any]:
        """Metadata for up to 50 videos per call (statistics, duration)."""
        return self.get(
            "videos",
            part="snippet,contentDetails,statistics",
            id=",".join(video_ids[:50]),
        )

    def _paginate(
        self, endpoint: str, params: dict[str, Any], *, max_pages: int
    ) -> Iterator[dict[str, Any]]:
        token: str | None = None
        for _ in range(max(1, max_pages)):
            page = self.get(endpoint, pageToken=token, **params)
            yield page
            token = page.get("nextPageToken")
            if not token:
                return
