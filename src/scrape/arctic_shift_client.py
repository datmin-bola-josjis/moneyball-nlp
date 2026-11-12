"""Arctic Shift client: cached from the first request, with adaptive pacing.

Arctic Shift returns ``{"data": null, "error": "Timeout. Maybe slow down a bit"}``
when it is rate limiting, and it does so with a latency of 1 to 4 seconds. The
message is misleading: it is not a network timeout, and raising the request
timeout makes the client slower without fixing anything. Measured 2026-11-12:
an identical query that returned the rate-limit error succeeded after a pause.

So this client treats that message as backpressure, waits longer, and retries.
It never increases the socket timeout in response to it.

Everything is cached to disk before the response is parsed, so a run that dies
halfway keeps what it already paid for.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://arctic-shift.photon-reddit.com/api"
USER_AGENT: Final[str] = "moneyball-nlp/0.1 (academic research; 4-person student project)"

DEFAULT_TIMEOUT: Final[int] = 90
START_DELAY: Final[float] = 8.0
MAX_DELAY: Final[float] = 240.0
BACKOFF_FACTOR: Final[float] = 1.8
MAX_ATTEMPTS: Final[int] = 6

# Arctic Shift signals backpressure with this message, not with HTTP 429.
RATE_LIMIT_MARKERS: Final[tuple[str, ...]] = (
    "slow down",
    "timeout. maybe",
    "too many",
    "rate limit",
)

# Client errors that will never succeed on retry. Retrying these wastes the
# rate-limit budget, which is the scarce resource here.
#
# 422 is deliberately ABSENT: Arctic Shift returns HTTP 422 carrying
# "Timeout. Maybe slow down a bit" when it is throttling, so that status is
# backpressure and must be retried, not rejected.
NON_RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({400, 401, 403, 404})


class ArcticShiftError(RuntimeError):
    """Raised when a request cannot succeed after the retry budget."""


class ArcticShiftClient:
    """Query Arctic Shift with caching and adaptive backpressure handling.

    Parameters
    ----------
    cache_dir:
        Where responses are stored. A cache hit performs no network request.
    start_delay:
        Initial pause between requests, in seconds. Increases on backpressure
        and decays slowly on success.
    max_delay:
        Ceiling for the adaptive delay.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        start_delay: float = START_DELAY,
        max_delay: float = MAX_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = start_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self._last_request_at = 0.0
        self.network_requests = 0
        self.cache_hits = 0
        self.backpressure_events = 0

    # ------------------------------------------------------------- internals

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        parts = [endpoint.replace("/", "-")]
        for key in sorted(params):
            parts.append(f"{key}={params[key]}")
        safe = "_".join(parts).replace("/", "-").replace(":", "").replace(" ", "")
        if len(safe) > 180:  # stay well inside filesystem limits
            import hashlib

            digest = hashlib.sha256(safe.encode()).hexdigest()[:16]
            safe = safe[:150] + "_" + digest
        return self.cache_dir / f"{safe}.json"

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _is_backpressure(self, payload: dict[str, Any]) -> bool:
        error = str(payload.get("error") or "").lower()
        if not error:
            return False
        return any(marker in error for marker in RATE_LIMIT_MARKERS)

    def _fetch(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._wait()
        self.network_requests += 1
        self._last_request_at = time.monotonic()
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            return {
                "data": None,
                "error": f"HTTP {exc.code}: {body}",
                "_status": exc.code,
            }
        except (URLError, TimeoutError) as exc:
            return {"data": None, "error": f"network: {exc}"}

    # ----------------------------------------------------------------- public

    def get(self, endpoint: str, *, force: bool = False, **params: Any) -> dict[str, Any]:
        """Return parsed JSON for an endpoint, using the cache when present."""
        cache_path = self._cache_path(endpoint, params)

        if cache_path.exists() and not force:
            try:
                self.cache_hits += 1
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("corrupt cache entry, refetching: %s", cache_path.name)

        query = urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{BASE_URL}/{endpoint}?{query}"

        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            payload = self._fetch(url)
            data = payload.get("data")

            if data:
                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                # Successful call: ease the delay back down gently.
                self.delay = max(START_DELAY, self.delay * 0.7)
                return payload

            last_error = str(payload.get("error") or "empty data")
            status = payload.get("_status")

            # A malformed request never succeeds on retry. Raising immediately
            # also protects the rate-limit budget, which is the scarce resource.
            if status in NON_RETRYABLE_STATUS:
                raise ArcticShiftError(f"request rejected ({last_error[:160]})")

            self.backpressure_events += 1
            # Backpressure, not a network timeout: wait, do not raise timeout.
            self.delay = min(self.max_delay, self.delay * BACKOFF_FACTOR)
            logger.info(
                "backpressure on attempt %d/%d (%s); next delay %.0fs",
                attempt,
                MAX_ATTEMPTS,
                last_error[:60],
                self.delay,
            )

        raise ArcticShiftError(
            f"gave up after {MAX_ATTEMPTS} attempts on {endpoint}: {last_error}"
        )

    def posts(self, **params: Any) -> dict[str, Any]:
        return self.get("posts/search", **params)

    def comments(self, **params: Any) -> dict[str, Any]:
        return self.get("comments/search", **params)

    def comment_tree(self, link_id: str, **params: Any) -> dict[str, Any]:
        return self.get("comments/tree", link_id=link_id, **params)
