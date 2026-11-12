"""Minimal FotMob HTTP client: rate limited, retried, cached, resumable.

Design constraints come from AGENTS.md:

  * at least one second between requests
  * retries with exponential backoff
  * responses cached on disk so a rerun does not re-hit the network
  * a sensible User-Agent

The cache doubles as the resume mechanism. A 340-player fetch takes minutes;
if it dies halfway, the next run only fetches what is missing.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

BASE_URL: Final[str] = "https://www.fotmob.com/api/data"
USER_AGENT: Final[str] = (
    "moneyball-nlp/0.1 (academic project; contact via repository)"
)
DEFAULT_TIMEOUT: Final[int] = 30
DEFAULT_MIN_INTERVAL: Final[float] = 1.0
MAX_RETRIES: Final[int] = 4
BACKOFF_BASE: Final[float] = 2.0
# 404 and 403 will not fix themselves; retrying them only wastes the budget.
NON_RETRYABLE: Final[frozenset[int]] = frozenset({400, 401, 403, 404, 410})


class FotMobError(RuntimeError):
    """Raised when a FotMob request fails permanently."""


class FotMobClient:
    """Fetches FotMob JSON with polite pacing and an on-disk cache.

    Parameters
    ----------
    cache_dir:
        Directory for cached responses. Created if missing.
    min_interval:
        Minimum seconds between two network requests. Never lower than 1.0.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if min_interval < 1.0:
            raise ValueError(
                f"min_interval must be >= 1.0s per AGENTS.md, got {min_interval}"
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_request_at: float = 0.0
        self.network_requests: int = 0
        self.cache_hits: int = 0

    # ------------------------------------------------------------- internals

    def _cache_path(self, endpoint: str, params: dict[str, Any]) -> Path:
        parts = [endpoint] + [f"{key}={params[key]}" for key in sorted(params)]
        safe = "_".join(parts).replace("/", "-").replace("%", "pct")
        return self.cache_dir / f"{safe}.json"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _request(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self._throttle()
        self.network_requests += 1
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    # ----------------------------------------------------------------- public

    def get(
        self,
        endpoint: str,
        *,
        force: bool = False,
        **params: Any,
    ) -> dict[str, Any]:
        """Fetch an endpoint, using and filling the cache.

        Parameters
        ----------
        endpoint:
            Path below ``/api/data``, e.g. ``"playerData"``.
        force:
            Ignore an existing cache file and refetch.
        **params:
            Query parameters, e.g. ``id=737066``.
        """
        cache_path = self._cache_path(endpoint, params)

        if cache_path.exists() and not force:
            try:
                self.cache_hits += 1
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("corrupt cache entry, refetching: %s", cache_path.name)

        query = "&".join(f"{key}={value}" for key, value in params.items())
        url = f"{BASE_URL}/{endpoint}?{query}" if query else f"{BASE_URL}/{endpoint}"

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                payload = self._request(url)
            except HTTPError as exc:
                if exc.code in NON_RETRYABLE:
                    raise FotMobError(
                        f"{url} returned HTTP {exc.code}; not retrying"
                    ) from exc
                last_error = exc
                logger.warning(
                    "HTTP %s on %s (attempt %d/%d)",
                    exc.code,
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                )
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning(
                    "request failed on %s (attempt %d/%d): %s",
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                )
            else:
                cache_path.write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                return payload

            if attempt < MAX_RETRIES - 1:
                delay = BACKOFF_BASE ** (attempt + 1)
                logger.info("backing off %.1fs", delay)
                time.sleep(delay)

        raise FotMobError(f"exhausted {MAX_RETRIES} retries for {url}: {last_error}")

    def player(self, player_id: int | str, *, force: bool = False) -> dict[str, Any]:
        return self.get("playerData", force=force, id=player_id)
