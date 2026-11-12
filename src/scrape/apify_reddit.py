"""Reddit retrieval through the Apify `automation-lab/reddit-scraper` actor.

Opt-in alternative to the OAuth client in `reddit.py`. It exists because the Reddit
Data API approval did not arrive in time and the team accepted the risk of using a
third-party marketplace actor (AGENTS.md rule 12 and PRD §13 are knowingly
relaxed here; see docs/tahap-b-reddit.md §3).

What this module will not do, so the rest of the pipeline stays honest:
  * it never invents texts - a record exists only if the actor returned it;
  * it reports per-player counts and names players with zero texts, so an empty
    scrape cannot pass as success;
  * it keeps the raw actor payload in `data/raw/`, untouched, for audit;
  * it maps the actor's fields onto the same `TextRecord` shape as the OAuth
    path, so Stage C cannot tell which provider produced a record;
  * it records `source="reddit_apify"` per row, so the report can state exactly
    which provider produced which text.

Requires `APIFY_TOKEN` in `.env`. Cost is pay-per-result; `estimate_cost()` is
printed before the first live run and the run refuses to start above
`apify.max_cost_usd` from config.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.config import ROOT, env, load_config
from src.scrape.aliases import AliasIndex
from src.scrape.players import Player
from src.scrape.reddit import (
    TextRecord,
    epoch_window,
    player_club_subreddits,
    unique_raw_dir,
    write_jsonl,
)
from src.scrape.textops import (
    clean_text,
    is_bot_like,
    is_english,
    split_sentences,
    text_hash,
    word_count,
)

log = logging.getLogger("reddit.apify")

ACTOR = "automation-lab/reddit-scraper"
API = "https://api.apify.com/v2"
# FREE-tier pay-per-event prices, from the actor README (2026-11-17 schedule).
PRICE_PER_POST = 0.00115
PRICE_PER_COMMENT = 0.00075
PRICE_START = 0.003


class ApifyError(RuntimeError):
    pass


def estimate_cost(n_players: int, posts_per_player: int, comments_per_post: int) -> dict:
    """Worst-case cost before running, so nobody discovers the bill afterwards.

    Comments are billed per *post*, not per player: the actor pulls up to
    `maxCommentsPerPost` from every post it returns, so the comment count is
    posts x comments_per_post. That product is what blows a budget up, which is
    why the estimate uses it rather than a per-player figure.
    """
    posts = n_players * posts_per_player
    comments = posts * comments_per_post
    total = n_players * PRICE_START + posts * PRICE_PER_POST + comments * PRICE_PER_COMMENT
    return {
        "players": n_players,
        "posts": posts,
        "comments": comments,
        "usd": round(total, 2),
    }


class ApifyClient:
    def __init__(self, token: str | None = None, session: requests.Session | None = None):
        self.token = token or env("APIFY_TOKEN")
        self._session = session or requests.Session()
        # Bearer header, not `?token=`: a token in the query string ends up in
        # request logs and proxy history, which is exactly how it leaked into
        # this project's own verbose output during the first live run.
        self._session.headers["Authorization"] = f"Bearer {self.token}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._session.get(f"{API}{path}", params=params or {}, timeout=120)
        if resp.status_code != 200:
            raise ApifyError(f"GET {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def credit_remaining(self, free_credits_usd: float = 5.0) -> float | None:
        """Dollars left in the current monthly cycle, or None if unreadable.

        The config cap is a promise to the team; this is the fact. Without it a
        cap can be larger than the balance and every run dies at the payment
        step halfway through a player list.
        """
        try:
            data = self._get("/users/me/limits")["data"]["current"]
        except (ApifyError, KeyError):
            return None
        used = float(data.get("monthlyUsageUsd") or 0.0)
        return round(max(free_credits_usd - used, 0.0), 2)

    def input_properties(self) -> set[str]:
        """Property names the actor's published build actually accepts.

        The actor silently ignores unknown keys: on the first live pilot a
        `searchQueries` key (not in its schema - it takes `searchQuery`) was
        dropped, the search never ran, and the run returned the subreddit's hot
        posts instead. Validating here turns that silent failure into an error.
        """
        if getattr(self, "_props", None):
            return self._props
        build = self._get(f"/acts/{ACTOR.replace('/', '~')}/builds")["data"]["items"][0]
        payload = self._get(
            f"/acts/{ACTOR.replace('/', '~')}/builds/{build['id']}"
        )["data"]["inputSchema"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        self._props = set(payload.get("properties", {}))
        return self._props

    def validate_input(self, actor_input: dict) -> None:
        unknown = sorted(set(actor_input) - self.input_properties())
        if unknown:
            raise ApifyError(
                f"actor does not accept these input keys: {unknown}. "
                "Unknown keys are silently ignored by Apify and the run would "
                "return unrelated data."
            )

    def run_actor(self, actor_input: dict, timeout_s: int = 900) -> dict:
        self.validate_input(actor_input)
        run = self._session.post(
            f"{API}/acts/{ACTOR.replace('/', '~')}/runs",
            params={"timeout": timeout_s},
            json=actor_input,
            timeout=120,
        )
        if run.status_code not in (200, 201):
            raise ApifyError(f"run failed HTTP {run.status_code}: {run.text[:300]}")
        payload = run.json()["data"]
        run_id, dataset_id = payload["id"], payload["defaultDatasetId"]

        # Poll the run status; the API has no blocking wait for arbitrary actors.
        import time

        try:
            return self._await_run(run_id, dataset_id, timeout_s)
        except BaseException:
            # Ctrl-C or a kill must not leave the actor billing in the background:
            # an interrupted local run kept a RUNNING actor alive and spent more.
            self.abort_run(run_id)
            raise

    def abort_run(self, run_id: str) -> None:
        try:
            self._session.post(f"{API}/actor-runs/{run_id}/abort", timeout=60)
            log.warning("aborted actor run %s", run_id)
        except Exception as exc:  # best effort: never mask the original error
            log.error("could not abort actor run %s: %s", run_id, exc)

    def _await_run(self, run_id: str, dataset_id: str, timeout_s: int) -> dict:
        import time

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self._get(f"/actor-runs/{run_id}")["data"]["status"]
            if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
                if status != "SUCCEEDED":
                    raise ApifyError(f"actor run {run_id} ended {status}")
                break
            time.sleep(5)
        else:
            raise ApifyError(f"actor run {run_id} did not finish within {timeout_s}s")

        return {"run_id": run_id, "dataset_id": dataset_id}

    def dataset_items(self, dataset_id: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            page = self._get(
                f"/datasets/{dataset_id}/items",
                {"format": "json", "clean": 1, "offset": offset, "limit": 1000},
            )
            if not isinstance(page, list) or not page:
                return items
            items.extend(page)
            if len(page) < 1000:
                return items
            offset += 1000


# ------------------------------------------------------------------ input build
def build_input(player: Player, index: AliasIndex, cfg: dict) -> dict:
    """One actor input per player: a search per alias, scoped to the club sub.

    The actor searches posts (not comments) and then pulls each post's comment
    tree, so the unit we want is reached in two hops. `searchSubreddit` restricts
    the search; comments are fetched per returned post.
    """
    subs = player_club_subreddits(player)
    alias = index.query_terms(player, max_terms=1)
    # `searchQuery` (singular string) is the only search key in the actor's
    # schema. Sending `searchQueries` is silently ignored and the actor then
    # lists the subreddit's hot posts instead of searching - which is exactly
    # what happened on the first live pilot and produced zero texts.
    payload = {
        "searchQuery": (alias or [player.name])[0],
        # Relative window only: Reddit search cannot target an absolute date
        # range, so the widest window that still overlaps the season is used and
        # the exact season boundary is enforced locally.
        "sort": cfg.get("search_sort", "top"),
        "timeFilter": cfg.get("search_time_filter", "year"),
        "maxPostsPerSource": int(cfg.get("max_posts_per_player", 5)),
        "includeComments": True,
        "maxCommentsPerPost": int(cfg.get("max_comments_per_post", 12)),
        "commentDepth": 3,
        "outputFormat": "default",
        "deduplicatePosts": True,
    }
    if subs:
        payload["searchSubreddit"] = subs[0]
    return payload


# --------------------------------------------------------------------- mapping
def _utc(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


_DELETED = {"[deleted]", "[removed]"}


def _absolute(permalink: str | None) -> str:
    """The actor returns an absolute permalink; the comment path returns a path.

    Prefixing unconditionally produced `https://www.reddit.comhttps://...` on the
    first live run, so both shapes are handled here.
    """
    if not permalink:
        return ""
    if permalink.startswith(("http://", "https://")):
        return permalink
    return f"https://www.reddit.com{permalink}"


def _subreddit_of(item: dict, by_post: dict[str, str]) -> str:
    """Resolve the subreddit for a record.

    Comment items in the actor's `default` schema carry no `subreddit`, so it is
    inherited from the parent post, then read out of the permalink. Leaving it
    blank would silently break the per-subreddit relevance table in the report.
    """
    name = item.get("subreddit")
    if name:
        return str(name)
    post_id = str(item.get("postId") or "")
    if post_id and post_id in by_post:
        return by_post[post_id]
    # Permalinks arrive both as `/r/<sub>/...` and as absolute URLs, so the path
    # is parsed rather than indexed positionally.
    path = urlparse(_absolute(item.get("permalink"))).path
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "r":
        return parts[1]
    return ""


def records_from_items(
    items: list[dict],
    player: Player,
    index: AliasIndex,
    min_words: int,
    window: tuple[float, float],
    league_clubs: list[str] | None = None,
    club_subreddits: list[str] | None = None,
    quota: int | None = None,
) -> list[TextRecord]:
    """Map actor output onto TextRecord with the same filters as the OAuth path.

    The actor returns whole posts and their comment trees, so this function has
    to apply every rule the OAuth reader applies - otherwise the two providers
    would produce datasets with different definitions of "a text":
      * bot, `[deleted]`, `[removed]` and non-English units are dropped;
      * an ambiguous alias needs club context (AGENTS.md rule 17);
      * at most `quota` units per player, so a star cannot dominate volume;
      * a post or comment is kept only if it names the player (rule 3).
    """
    season_start, season_end = window
    league_clubs = league_clubs or []
    club_subs = {s.lower() for s in (club_subreddits or [])}
    records: list[TextRecord] = []
    seen_hashes: set[str] = set()
    units = 0

    # Posts first so comments can inherit their subreddit (actor omits it).
    by_post: dict[str, str] = {}
    for item in items:
        if item.get("type") == "post" and item.get("id") and item.get("subreddit"):
            by_post[str(item["id"])] = str(item["subreddit"])

    for item in items:
        if quota is not None and units >= quota:
            break
        # Posts are carriers, not evidence: PRD §8 locks `unit_type` to
        # comment/sentence/transcript_segment, and the OAuth path stores only
        # comments. Keeping their text would also double-count a mention that
        # reappears in the comments.
        if item.get("type") != "comment":
            continue
        raw_body = (item.get("body") or item.get("selfText") or "").strip()
        if not raw_body or raw_body in _DELETED:
            continue
        cleaned = clean_text(raw_body)
        if word_count(cleaned) < min_words:
            continue
        if not is_english(cleaned):
            continue
        if is_bot_like(str(item.get("author") or ""), cleaned):
            continue
        created = _utc(item.get("createdAt"))
        if not (season_start <= created <= season_end):
            continue

        subreddit = _subreddit_of(item, by_post)
        in_club_sub = subreddit.lower() in club_subs
        alias = index.find_mentions(cleaned, player.player_id)
        if not index.resolves(alias, cleaned, player.player_id, league_clubs, in_club_sub):
            continue
        body_hash = text_hash(cleaned)
        if body_hash in seen_hashes:
            continue
        seen_hashes.add(body_hash)
        units += 1

        item_id = str(item.get("id") or body_hash)
        # Same convention as the OAuth path: the player is part of the key, so
        # one text naming two sample players yields two distinct records.
        text_id = f"ap_{item_id}_{player.player_id}"
        post_id = str(item.get("postId") or item.get("id") or "")
        shared = dict(
            player_id=player.player_id,
            source="reddit_apify",
            text_raw=raw_body,
            language="en",
            created_at=datetime.fromtimestamp(created, tz=timezone.utc).isoformat(
                timespec="seconds"
            ),
            url=_absolute(item.get("permalink")),
            thread_id=post_id,
            subreddit=subreddit,
            engagement=int(item.get("score") or 0),
        )
        records.append(
            TextRecord(
                text_id=text_id,
                unit_type="comment",
                text_clean=cleaned,
                text_clean_hash=body_hash,
                matched_alias=alias,
                parent_text_id=None,
                **shared,
            )
        )
        for i, sentence in enumerate(split_sentences(cleaned)):
            sentence_alias = index.find_mentions(sentence, player.player_id)
            if not index.resolves(
                sentence_alias, sentence, player.player_id, league_clubs, in_club_sub
            ):
                continue
            records.append(
                TextRecord(
                    text_id=f"{text_id}_s{i}",
                    unit_type="sentence",
                    text_clean=sentence,
                    text_clean_hash=text_hash(sentence),
                    matched_alias=sentence_alias,
                    parent_text_id=text_id,
                    **shared,
                )
            )
    return records


# ------------------------------------------------------------------------ run
def run(
    players: list[Player],
    client: ApifyClient | None = None,
    tag: str = "apify",
    root: Path | None = None,
) -> Path:
    cfg = load_config()["text_sources"]["reddit"].get("apify", {})
    if not cfg.get("enabled", False):
        raise SystemExit(
            "apify provider disabled: set text_sources.reddit.apify.enabled: true "
            "in config/config.yaml to use it"
        )
    est = estimate_cost(
        len(players),
        int(cfg.get("max_posts_per_player", 5)),
        int(cfg.get("max_comments_per_post", 12)),
    )
    cap = float(cfg.get("max_cost_usd", 5.0))
    log.warning(
        "apify REDDIT SCRAPER: %d players, ~%d posts, ~%d comments, est. $%.2f (cap $%.2f)",
        est["players"], est["posts"], est["comments"], est["usd"], cap,
    )
    if est["usd"] > cap:
        raise SystemExit(
            f"estimated ${est['usd']} exceeds apify.max_cost_usd=${cap}. "
            "Lower max_posts_per_player / max_comments_per_post or raise the cap."
        )

    client = client or ApifyClient()
    remaining = client.credit_remaining() if hasattr(client, "credit_remaining") else None
    if remaining is not None and est["usd"] > remaining:
        raise SystemExit(
            f"estimated ${est['usd']} but only ${remaining} Apify credit remains this "
            "cycle. Reduce the player count or max_posts_per_player; raising "
            "max_cost_usd will not create credit."
        )
    index = AliasIndex.build(players)
    window = epoch_window()
    min_words = int(load_config()["text_sources"]["reddit"].get("min_words", 8))
    league_clubs = load_config()["league"].get("clubs", [])
    quota = int(load_config()["text_sources"]["reddit"].get("max_texts_per_player", 60))

    base = root or ROOT
    raw_dir = unique_raw_dir(tag, base=base / "data" / "raw" / "reddit")
    all_records: list[TextRecord] = []
    per_player: dict[str, int] = {}

    for n, player in enumerate(players, start=1):
        actor_input = build_input(player, index, cfg)
        (raw_dir / f"{player.player_id}.input.json").write_text(
            json.dumps(actor_input, indent=2), encoding="utf-8"
        )
        result = client.run_actor(actor_input)
        items = client.dataset_items(result["dataset_id"])
        (raw_dir / f"{player.player_id}.items.json").write_text(
            json.dumps(items, indent=2), encoding="utf-8"
        )
        records = records_from_items(
            items,
            player,
            index,
            min_words,
            window,
            league_clubs=league_clubs,
            club_subreddits=player_club_subreddits(player),
            quota=quota,
        )
        per_player[player.name] = sum(1 for r in records if r.unit_type == "comment")
        all_records.extend(records)
        log.info(
            "[%d/%d] %-28s %3d items -> %3d comments",
            n, len(players), player.name, len(items), per_player[player.name],
        )

    rows = [asdict(r) for r in all_records]
    write_jsonl(rows, raw_dir / "texts.jsonl")
    empty = sorted(name for name, c in per_player.items() if c == 0)
    summary = {
        "run": raw_dir.name,
        "provider": ACTOR,
        "players": len(players),
        "comments": sum(1 for r in all_records if r.unit_type == "comment"),
        "sentences": sum(1 for r in all_records if r.unit_type == "sentence"),
        "estimated_usd": est["usd"],
        "per_player": per_player,
        "players_without_text": empty,
    }
    (raw_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    interim = base / "data" / "interim" / f"texts_reddit_{tag}.jsonl"
    write_jsonl(rows, interim)
    log.info(
        "apify kept %d comments / %d sentences -> %s (raw: %s)",
        summary["comments"], summary["sentences"], interim, raw_dir.name,
    )
    if empty:
        log.warning("no texts for %d players: %s", len(empty), ", ".join(empty[:10]))
    return interim
