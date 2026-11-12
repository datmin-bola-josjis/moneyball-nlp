"""Reddit retrieval through the Arctic Shift archive (Stage B, third-party path).

Used because OAuth is unavailable (no Data API approval, empty credentials) and the
Apify actor was rejected. Arctic Shift (https://arctic-shift.photon-reddit.com)
serves archived Reddit JSON without authentication, so no `REDDIT_*` value in
`.env` is needed. This knowingly relaxes AGENTS.md rule 12 / PRD §13; the team
decision and its limits are recorded in docs/decisions.md, and the report must
state them.

Measured constraints (2026-11-12, UA `moneyball-nlp/0.1 (coursework)`):
  * `/api/comments/search` works for club subreddits; `soccer` and `PremierLeague`
    answer 422 at every limit, so league subreddits are never queried here;
  * `/api/posts/search` answers 422 for every title query, so it is not used;
  * a multi-word `body=` phrase always answers 422 - only single tokens are sent;
  * `limit=100` answers 422 for rare terms but 200 for common ones, so the limit
    is lowered step by step instead of retried at the same size;
  * ~40% of first attempts are 422, hence retry with a gap plus a disk cache.

`body=` is a *substring* match, not a word match, which is why every comment still
goes through `_records_from_comment`: whole-word matching and ambiguous-surname
disambiguation (rule 17) stay in one place, shared with the OAuth path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

import requests

from src.config import ROOT, load_config
from src.scrape.aliases import AliasIndex, normalize
from src.scrape.players import Player
from src.scrape.reddit import (
    TextRecord,
    _records_from_comment,
    epoch_window,
    player_club_subreddits,
    unique_raw_dir,
    write_jsonl,
)
from src.scrape.reddit_client import keep_comment

log = logging.getLogger("reddit.arctic")

API = "https://arctic-shift.photon-reddit.com"
USER_AGENT = "moneyball-nlp/0.1 (coursework)"
# 422 is this archive's "server busy / too heavy" answer, not "no results":
# an unknown subreddit is a plain `200 []`. Treating it as terminal loses data.
RETRYABLE = {422, 429, 500, 502, 503, 504}
# Refusals: retrying cannot help, and the plan says a 403 stops the run.
FATAL = {401, 403}
MIN_INTERVAL = 1.0  # AGENTS.md: >= 1 s per request, no exceptions

class ArcticShiftError(RuntimeError):
    pass

class ArcticShiftBlocked(ArcticShiftError):
    """Access refused by the archive. The run must stop instead of limping on."""

# --------------------------------------------------------------- query build
def query_terms(player: Player) -> list[str]:
    """The participation token of the name - the only shape this archive accepts.

    Two-word `body=` phrases answer 422 unconditionally, so the last token of the
    player's name is used ("Jørgen Strand Larsen" -> "larsen"). That closes every
    multi-word alias in the locked sample: the surname is what the text contains,
    and `find_mentions` verifies the full alias afterwards.
    """
    tokens = normalize(player.name).split()
    return [tokens[-1]] if tokens else []

def player_subreddits(player: Player) -> list[str]:
    """The player's club subreddits only.

    `subreddits_league` is deliberately excluded: r/soccer and r/PremierLeague are
    not body-searchable in this archive (422 at every limit), so adding them would
    only burn retries.
    """
    return player_club_subreddits(player)

# The archive returns Reddit's full comment object - ~72 fields including
# `profile_img` (the commenter's avatar URL), `link_author` (the post author),
# `approved_by`/`banned_by`/`mod_reason_by` (moderator names), `author_flair_*`.
# A blacklist missed `profile_img` and `link_author` on the first live pilot, so
# only the fields the pipeline actually reads are kept (AGENTS.md rule 11).
_FIELDS_FOR_FILTER = ("author", "body", "stickied", "distinguished")
_FIELDS_KEPT = (
    "id", "body", "created_utc", "subreddit", "score", "permalink", "link_id", "stickied",
)

def _annotate(items: list[dict]) -> list[dict]:
    """Keep the fields the pipeline needs, record the drop verdict, drop identity.

    `keep_comment` needs `author` to recognise bots and moderators, but nothing on
    disk may carry a username or an avatar URL. The verdict is therefore written as
    `_skip` first, then every identity-bearing field is discarded. Idempotent: an
    already-tagged row keeps its verdict.
    """
    out = []
    for item in items:
        skipped = item.get("_skip")
        if skipped is None:
            view = {k: item.get(k) for k in _FIELDS_FOR_FILTER}
            skipped = not keep_comment(view)
        kept = {k: item[k] for k in _FIELDS_KEPT if k in item}
        kept["_skip"] = skipped
        out.append(kept)
    return out

# -------------------------------------------------------------------- client
class ArcticShiftClient:
    def __init__(self, session: requests.Session | None = None, cache_dir: Path | None = None):
        cfg = load_config()["text_sources"]["reddit"]["arctic_shift"]
        self.limit_ladder = [int(v) for v in cfg.get("limit_ladder", [100, 25])]
        self.retry_gap = float(cfg.get("retry_gap_seconds", 10))
        self.max_attempts = int(cfg.get("max_attempts", 4))
        # A reset header can ask for minutes; cap it so one bad answer cannot
        # stall a run forever, and let config raise the ceiling.
        self.max_reset_wait = float(cfg.get("max_reset_wait_seconds", 120))
        # Config may only raise the floor, never lower it.
        self.min_interval = max(MIN_INTERVAL, float(cfg.get("rate_limit_seconds", MIN_INTERVAL)))
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._cache_dir = Path(cache_dir or ROOT / cfg.get("cache_dir", "data/raw/reddit/arctic/cache"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0
        self.requests_made = 0
        self.last_limit = self.limit_ladder[0] if self.limit_ladder else 0

    def _cache_path(self, params: dict) -> Path:
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
        return self._cache_dir / f"{key}.json"

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _params(self, subreddit: str, term: str, after: float,
                before: float | None, limit: int) -> dict:
        params: dict = {
            "subreddit": subreddit,
            "body": term,
            "after": int(after),
            "limit": limit,
            "sort": "desc",
        }
        if before is not None:
            params["before"] = int(before)
        return params

    def _cached_page(self, subreddit: str, term: str, after: float,
                     before: float | None) -> list[dict] | None:
        """Return a cached answer for any rung of the ladder, or None.

        Checking only the current rung before requesting it meant a cheap page
        cached at `limit=25` was preceded by a fresh `limit=100` request on every
        rerun - eight wasted requests on one pilot player. A cache hit must not
        touch the network at all.
        """
        for limit in self.limit_ladder:
            cache_file = self._cache_path(self._params(subreddit, term, after, before, limit))
            if cache_file.exists():
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.last_limit = limit
                return data
        return None

    def _await_reset(self, resp: requests.Response) -> float:
        """Wait out the archive's advertised rate-limit reset.

        The README's contract: after a rate-limited answer, wait for
        `X-RateLimit-Reset` (seconds) or `X-RateLimit-Reset-At` (epoch ms) before
        the next request. Sending early is what turns one 422 into eight - the
        first probe showed a 35 s reset while the client retried after 10 s.

        The full reset is always honoured. If it exceeds `max_reset_wait_seconds`
        the run stops instead of quietly requesting too early; a header that
        cannot be parsed also stops, because guessing would break the same rule.
        """
        reset_at = resp.headers.get("x-ratelimit-reset-at")
        reset_seconds = resp.headers.get("x-ratelimit-reset")
        wait: float | None = None
        if reset_at:
            try:
                wait = float(reset_at) / 1000.0 - time.time()
            except (TypeError, ValueError):
                wait = None  # malformed: fall through to the seconds header
        if wait is None and reset_seconds:
            try:
                wait = float(reset_seconds)
            except (TypeError, ValueError):
                wait = None
        if wait is None:
            raise ArcticShiftBlocked(
                "rate-limited without a usable X-RateLimit-Reset header "
                f"(reset={reset_seconds!r}, reset-at={reset_at!r}) - stopping rather "
                "than guessing when the archive allows another request"
            )
        wait = max(0.0, wait)
        if wait > self.max_reset_wait:
            raise ArcticShiftBlocked(
                f"rate-limit reset in {wait:.0f}s exceeds max_reset_wait_seconds="
                f"{self.max_reset_wait:.0f}; stopping instead of requesting early. "
                "Raise the ceiling or rerun later - cached pages are not refetched."
            )
        if wait:
            log.warning("rate limited: waiting %.0fs for the reset header", wait)
            time.sleep(wait)
        return wait

    def search_comments(
        self, subreddit: str, term: str, after: float, before: float | None = None
    ) -> list[dict]:
        """Comments in `subreddit` whose body contains `term`, within the window.

        `after`/`before` are sent as epoch integers, the format verified working
        here. The archive also documents ISO dates, but a probe answered 422 and
        422 is this archive's load signal, so it proves nothing either way - no
        ISO claim is made in the docs.

        The caller must pass `before` on the first page too. `sort=desc` starts at
        the newest archived row, so `after` alone returns post-season rows that the
        season filter then throws away; that is how the first pilot handed one
        player an empty page and zero comments.

        An empty list is a real answer (unknown subreddit, no matches). Only a
        non-retryable status or an exhausted ladder raises, so the caller can tell
        "nothing found" from "could not ask".
        """
        cached = self._cached_page(subreddit, term, after, before)
        if cached is not None:
            return cached

        last_status = 0
        for limit in self.limit_ladder:
            params = self._params(subreddit, term, after, before, limit)
            cache_file = self._cache_path(params)
            # The whole ladder was checked up front, so a re-check here is only
            # needed for a page another worker cached mid-run.
            if cache_file.exists():
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.last_limit = limit
                return data

            for attempt in range(self.max_attempts):
                if attempt:
                    # Exponential backoff (AGENTS.md): a fixed gap hammers a
                    # server that just told us it is overloaded.
                    time.sleep(self.retry_gap * 2 ** (attempt - 1))
                self._throttle()
                self.requests_made += 1
                try:
                    resp = self._session.get(
                        f"{API}/api/comments/search", params=params, timeout=120
                    )
                except requests.RequestException as exc:
                    last_status = 0
                    log.warning(
                        "request error (%d/%d) r/%s %r: %s",
                        attempt + 1, self.max_attempts, subreddit, term, exc,
                    )
                    continue
                if resp.status_code == 200:
                    body = resp.json()
                    raw = body.get("data") if isinstance(body, dict) else body
                    if raw is None:
                        # The archive sometimes answers 200 with
                        # {"data": null, "error": "Timeout..."}: that is a
                        # throttled answer, not an empty subreddit. Caching it
                        # would freeze an empty page into the run forever.
                        last_status = 200
                        log.warning(
                            "empty body (%d/%d) r/%s %r limit=%d: %s",
                            attempt + 1, self.max_attempts, subreddit, term, limit,
                            (body or {}).get("error", "") if isinstance(body, dict) else "",
                        )
                        # No 429 status here, so no reset contract to obey; the
                        # exponential backoff of the next attempt covers it.
                        continue
                    # Scrubbed and annotated before anything touches disk: the
                    # cache is as permanent as the raw run (rule 5), so it must
                    # already be free of usernames (rule 11).
                    data = _annotate(raw)
                    cache_file.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8"
                    )
                    self.last_limit = limit
                    return data
                last_status = resp.status_code
                if last_status in FATAL:
                    # 401/403 means the archive is refusing us: retrying other
                    # players keeps hitting the same wall, so this stops the run.
                    raise ArcticShiftBlocked(
                        f"HTTP {last_status} from {API} - access refused, not load. "
                        f"Stop and report; do not work around it. body: {resp.text[:200]}"
                    )
                if last_status not in RETRYABLE:
                    raise ArcticShiftError(
                        f"HTTP {last_status} r/{subreddit} {term!r} - parameter problem, "
                        f"not load; body: {resp.text[:200]}"
                    )
                # Only a 429 carries the reset contract (README); a 422/5xx is
                # ordinary load and is handled by the exponential backoff.
                if last_status == 429:
                    self._await_reset(resp)
                log.warning(
                    "HTTP %d (%d/%d) r/%s %r limit=%d",
                    last_status, attempt + 1, self.max_attempts, subreddit, term, limit,
                )
        raise ArcticShiftError(f"HTTP {last_status} r/{subreddit} {term!r} after limit ladder")

# --------------------------------------------------------------------- mapping
def records_from_comments(
    comments: list[dict],
    player: Player,
    index: AliasIndex,
    league_clubs: list[str],
    min_words: int,
    quota: int | None = None,
    seen_hashes: set[str] | None = None,
    source: str = "reddit_arctic",
) -> list[TextRecord]:
    """Map archive comments onto TextRecord using the OAuth path's filters.

    Rows already carry `_skip` from `_annotate`, which decided bot/deleted/stickied
    before the username was stripped. That verdict is honoured here; it is the only
    bot signal left after scrubbing. Untagged rows (a caller passing raw archive
    rows) still go through `keep_comment`.
    """
    seen = seen_hashes if seen_hashes is not None else set()
    records: list[TextRecord] = []
    units = 0
    for comment in comments:
        if quota is not None and units >= quota:
            break
        skipped = comment.get("_skip")
        if skipped is None:
            skipped = not keep_comment(comment)
        if skipped:
            continue
        thread = {
            "id": str(comment.get("link_id") or "").removeprefix("t3_"),
            "subreddit": comment.get("subreddit", ""),
        }
        made = _records_from_comment(
            comment, thread, player, index, league_clubs, min_words, seen, source=source
        )
        if made:
            records.extend(made)
            units += 1
    return records

# ------------------------------------------------------------------------ run
def run(
    players: list[Player],
    client: ArcticShiftClient | None = None,
    tag: str = "arctic",
    root: Path | None = None,
) -> Path:
    cfg = load_config()["text_sources"]["reddit"]["arctic_shift"]
    if cfg.get("enabled") is not True:
        raise SystemExit(
            "arctic_shift provider disabled: set text_sources.reddit.arctic_shift.enabled: "
            "true in config/config.yaml"
        )
    reddit_cfg = load_config()["text_sources"]["reddit"]
    min_words = int(reddit_cfg.get("min_words", 8))
    quota = int(reddit_cfg.get("max_texts_per_player", 60))
    max_pages = int(cfg.get("max_pages_per_term", 2))
    index = AliasIndex.build(players)
    league_clubs = load_config()["league"].get("clubs", [])
    client = client or ArcticShiftClient()

    # Epoch seconds: the format verified to filter here. Both bounds are needed
    # from the first request - `sort=desc` otherwise starts at the newest row.
    after, season_end = epoch_window()

    raw_dir = unique_raw_dir(f"arctic-{tag}", base=(root or ROOT) / "data" / "raw" / "reddit")
    all_records: list[TextRecord] = []
    per_player: dict[str, int] = {}
    failed_requests = 0
    requests_at_start = client.requests_made

    for n, player in enumerate(players, start=1):
        seen_hashes: set[str] = set()
        player_comments: list[dict] = []
        records: list[TextRecord] = []
        kept = 0
        for subreddit in player_subreddits(player):
            for term in query_terms(player):
                # Page 1 is bounded above by the season end as well; without it
                # the default `desc` order starts at the newest archived row,
                # which is often outside the season.
                cursor: float | None = season_end
                for _ in range(max_pages):
                    if kept >= quota:
                        break
                    try:
                        page = client.search_comments(subreddit, term, after, cursor)
                    except ArcticShiftBlocked:
                        # A refusal is not a per-player miss: stop so the run does
                        # not silently continue with an empty dataset.
                        raise
                    except ArcticShiftError as exc:
                        failed_requests += 1
                        log.warning("search failed r/%s %r: %s", subreddit, term, exc)
                        break
                    if not page:
                        break
                    player_comments.extend(page)
                    page_records = records_from_comments(
                        page, player, index, league_clubs, min_words,
                        quota=quota - kept, seen_hashes=seen_hashes,
                    )
                    records.extend(page_records)
                    kept += sum(1 for r in page_records if r.unit_type == "comment")
                    # A short page means the archive has nothing more for this
                    # term; a full page means walk to the next cursor.
                    if len(page) < client.last_limit:
                        break
                    cursor = float(min(int(c["created_utc"]) for c in page))
        # Annotated (bot verdict) then scrubbed, so no username is on disk even if
        # a client handed back untouched rows (rule 11).
        (raw_dir / f"{player.player_id}.comments.json").write_text(
            json.dumps(_annotate(player_comments), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        per_player[player.name] = sum(1 for r in records if r.unit_type == "comment")
        all_records.extend(records)
        log.info(
            "[%d/%d] %-28s %3d comments", n, len(players), player.name, per_player[player.name]
        )

    rows = [asdict(r) for r in all_records]
    write_jsonl(rows, raw_dir / "texts.jsonl")

    empty = sorted(name for name, count in per_player.items() if count == 0)
    summary = {
        "run": raw_dir.name,
        "provider": "arctic_shift",
        "players": len(players),
        "comments": sum(1 for r in all_records if r.unit_type == "comment"),
        "sentences": sum(1 for r in all_records if r.unit_type == "sentence"),
        "requests": client.requests_made - requests_at_start,
        "failed_requests": failed_requests,
        "season_window": [after, season_end],
        "per_player": per_player,
        "players_without_text": empty,
    }
    (raw_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Stable handoff name for the next stages; raw keeps every run.
    interim = (root or ROOT) / "data" / "interim" / f"texts_reddit_{tag}.jsonl"
    write_jsonl(rows, interim)
    log.info(
        "arctic kept %d comments / %d sentences from %d requests (%d failed) -> %s (raw: %s)",
        summary["comments"], summary["sentences"], summary["requests"],
        failed_requests, interim, raw_dir.name,
    )
    if empty:
        log.warning("no texts for %d players: %s", len(empty), ", ".join(empty[:10]))
    return interim
