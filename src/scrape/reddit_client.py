"""Authenticated, rate-limited, cached Reddit JSON client (Stage B).

Plain `requests` against the OAuth JSON endpoints instead of PRAW: PRAW is not
installed and its API churn buys nothing here. Every request obeys the project
rules - >= 1 s spacing, exponential backoff, disk cache under `data/raw/`,
honest User-Agent - because Reddit answers 403 to unauthenticated callers
(verified 2026-11-12: `/r/soccer/about.json` -> 403).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from src.config import ROOT, env, load_config
from src.scrape.textops import is_bot_like

log = logging.getLogger("reddit")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
MAX_ATTEMPTS = 3
MIN_INTERVAL = 1.0  # AGENTS.md: >= 1 s per request, no exceptions


class RedditError(RuntimeError):
    pass


class RedditClient:
    def __init__(self, session: requests.Session | None = None, cache_dir: Path | None = None):
        cfg = load_config()["text_sources"]["reddit"]
        self.user_agent = env("REDDIT_USER_AGENT")
        self._client_id = env("REDDIT_CLIENT_ID")
        self._client_secret = env("REDDIT_CLIENT_SECRET")
        # Config may only raise the floor, never lower it.
        self.min_interval = max(MIN_INTERVAL, float(cfg.get("rate_limit_seconds", MIN_INTERVAL)))
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = self.user_agent
        self._cache_dir = Path(cache_dir or ROOT / cfg.get("cache_dir", "data/raw/reddit"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._token: str | None = None
        self._token_expires = 0.0
        self._last_request = 0.0
        self.requests_made = 0

    # ------------------------------------------------------------------ auth
    def _auth(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        resp = self._session.post(
            TOKEN_URL,
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self.user_agent},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RedditError(
                f"Reddit token request failed: HTTP {resp.status_code}. "
                "Check REDDIT_CLIENT_ID/SECRET in .env and that the app is a "
                f"'script' app. Body: {resp.text[:200]}"
            )
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires = time.monotonic() + int(payload.get("expires_in", 3600)) - 60
        return self._token

    # ----------------------------------------------------------------- cache
    def _cache_path(self, url: str, params: dict) -> Path:
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()[:24]
        return self._cache_dir / f"{key}.json"

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    # ------------------------------------------------------------------- get
    def get(self, path: str, params: dict | None = None) -> dict | list:
        """GET an API path, or return the cached body without touching network.

        Cache is never overwritten, so `data/raw/` stays an immutable record of
        what Reddit actually returned on the first successful call.
        """
        params = params or {}
        cache_file = self._cache_path(path, params)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(2**attempt)
            self._throttle()
            try:
                resp = self._session.get(
                    f"{API}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._auth()}"},
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("request error (%s/3) %s: %s", attempt + 1, path, last_error)
                continue

            self.requests_made += 1
            if resp.status_code == 401:
                # Token rejected early - drop it and retry with a fresh one.
                self._token = None
                last_error = "HTTP 401"
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                last_error = f"HTTP {resp.status_code}"
                log.warning("backing off (%s/3) %s: %s", attempt + 1, path, last_error)
                if retry_after:
                    time.sleep(min(float(retry_after), 60))
                continue
            if resp.status_code == 404:
                raise RedditError(f"HTTP 404 for {path} {params} - subreddit or thread is gone")
            if resp.status_code != 200:
                raise RedditError(f"HTTP {resp.status_code} for {path} {params}: {resp.text[:200]}")

            body = resp.json()
            cache_file.write_text(json.dumps(body), encoding="utf-8")
            return body

        raise RedditError(f"giving up on {path} {params} after {MAX_ATTEMPTS} attempts ({last_error})")

    # -------------------------------------------------------------- helpers
    def subreddit_exists(self, name: str) -> bool:
        try:
            data = self.get(f"/r/{name}/about", {})
        except RedditError:
            return False
        return bool(data) and data.get("data", {}).get("subreddit_type") is not None


def keep_comment(comment: dict) -> bool:
    """Cheap pre-filter so bot/deleted comments never reach parsing."""
    body = (comment.get("body") or "").strip()
    if not body or body in {"[deleted]", "[removed]"}:
        return False
    if comment.get("stickied") or comment.get("distinguished") == "moderator":
        return False
    return not is_bot_like(comment.get("author") or "", body)
