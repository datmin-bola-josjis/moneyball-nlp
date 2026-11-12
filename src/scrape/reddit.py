"""Player-centric Reddit retrieval (Stage B, person B).

Rules enforced here, not in the caller:
  * queries are per player, per configured subreddit, bounded by season dates;
  * threads are split into comments, comments into sentences, and a sentence is
    kept only if it names the player *and* survives the context check for an
    ambiguous alias (AGENTS.md rules 2, 3, 17);
  * quota per player caps the volume so stars cannot dominate;
  * a run logs the number of texts kept per player, so an empty scrape is
    visible instead of silently "successful";
  * raw records land in a timestamped run directory and are never overwritten.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config import ROOT, load_config
from src.scrape.aliases import AliasIndex
from src.scrape.players import Player, club_key
from src.scrape.reddit_client import RedditClient, RedditError, keep_comment
from src.scrape.textops import (
    clean_text,
    is_english,
    split_sentences,
    text_hash,
    word_count,
)

log = logging.getLogger("reddit.retrieve")


@dataclass
class TextRecord:
    text_id: str
    player_id: str
    source: str
    unit_type: str  # comment | sentence
    text_raw: str
    text_clean: str
    text_clean_hash: str
    language: str
    created_at: str
    url: str
    thread_id: str
    subreddit: str
    engagement: int
    matched_alias: str
    parent_text_id: str | None = None


# --------------------------------------------------------------- query build
def season_bounds() -> tuple[datetime, datetime]:
    """Inclusive season window. The end date covers the whole final day."""
    league = load_config()["league"]
    start = datetime.fromisoformat(league["season_start"]).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(league["season_end"]).replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    return start, end


def epoch_window() -> tuple[float, float]:
    start, end = season_bounds()
    return start.timestamp(), end.timestamp()


def subreddits_for(player: Player | None) -> list[str]:
    """League subreddits plus the player's own club subreddit.

    Querying all 20 club subreddits for one player would cost hundreds of
    requests per player for a club he does not play for. `ponytail:` ceiling -
    rival-club discussion is picked up through r/soccer and r/PremierLeague.
    Widen to every club subreddit only if pilot recall looks low.
    """
    names: list[str] = []
    # Club subreddit first: highest density of player-specific discussion, and
    # the per-player quota is consumed in query order.
    names.extend(player_club_subreddits(player))
    names.extend(load_config()["text_sources"]["reddit"].get("subreddits_league", []))
    return list(dict.fromkeys(names))


def player_club_subreddits(player: Player | None) -> list[str]:
    if not player or not player.club:
        return []
    target = club_key(player.club)
    for key, subs in load_config()["text_sources"]["reddit"].get("subreddits_clubs", {}).items():
        if club_key(key) == target:
            return list(subs)
    return []


def search_query(term: str) -> str:
    """Exact-phrase Reddit search.

    No date operator here: Reddit dropped Cloudsearch `timestamp:` range syntax,
    so a range in `q` would be matched as literal text and return nothing. The
    season window is enforced on `created_utc` after the results arrive.
    """
    return f'"{term}"'


# -------------------------------------------------------------------- search
def search_threads(client: RedditClient, subreddit: str, term: str, keep: int) -> list[dict]:
    """Return up to `keep` thread payloads created inside the season window.

    `q` cannot express a date range, so pages are walked and every thread is
    filtered locally against `[season_start, season_end]`. Walking stops when the
    page budget (`max_pages_per_query`) is spent or Reddit returns no cursor.
    """
    season_start, season_end = epoch_window()
    cfg = load_config()["text_sources"]["reddit"]
    max_pages = int(cfg.get("max_pages_per_query", 3))
    found: list[dict] = []
    after = None
    for _ in range(max_pages):
        params = {
            "q": search_query(term),
            "restrict_sr": 1,
            "sort": "relevance",
            "t": "all",
            "limit": 100,
            "raw_json": 1,
        }
        if after:
            params["after"] = after
        body = client.get(f"/r/{subreddit}/search", params)
        listing = body.get("data", {}) if isinstance(body, dict) else {}
        for child in listing.get("children", []):
            data = child.get("data", {})
            created = float(data.get("created_utc") or 0)
            if not (season_start <= created <= season_end):
                continue
            found.append(data)
            if len(found) >= keep:
                return found
        after = listing.get("after")
        if not after:
            break
    return found


def comment_forest(client: RedditClient, thread_id: str) -> list[dict]:
    body = client.get(f"/comments/{thread_id}", {"limit": 200, "depth": 4, "sort": "top"})
    if not isinstance(body, list) or not body:
        return []
    comments: list[dict] = []
    stack = list(body[1].get("data", {}).get("children", []))
    while stack:
        child = stack.pop(0)
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {})
        if keep_comment(data):
            comments.append(data)
        replies = data.get("replies")
        if isinstance(replies, dict):
            stack.extend(replies.get("data", {}).get("children", []))
    return comments


# ------------------------------------------------------------------- extract
def extract_for_player(
    client: RedditClient,
    player: Player,
    index: AliasIndex,
    league_clubs: list[str],
    quota: int,
) -> list[TextRecord]:
    cfg = load_config()["text_sources"]["reddit"]
    min_words = int(cfg.get("min_words", 8))
    max_threads = int(cfg.get("max_threads_per_query", 3))
    records: list[TextRecord] = []
    seen_hashes: set[str] = set()
    seen_threads: set[str] = set()
    comment_count = 0

    for subreddit in subreddits_for(player):
        for term in index.query_terms(player):
            if comment_count >= quota:
                return records
            try:
                threads = search_threads(client, subreddit, term, max_threads)
            except RedditError as exc:
                log.warning("search failed r/%s %r: %s", subreddit, term, exc)
                continue
            for thread in threads:
                if comment_count >= quota:
                    return records
                thread_id = thread.get("id")
                if not thread_id or thread_id in seen_threads:
                    continue
                seen_threads.add(thread_id)
                try:
                    comments = comment_forest(client, thread_id)
                except RedditError as exc:
                    log.warning("comments failed %s: %s", thread_id, exc)
                    continue
                for comment in comments:
                    if comment_count >= quota:
                        return records
                    made = _records_from_comment(
                        comment,
                        thread,
                        player,
                        index,
                        league_clubs,
                        min_words,
                        seen_hashes,
                    )
                    if made:
                        records.extend(made)
                        comment_count += 1
    return records


def _records_from_comment(
    comment: dict,
    thread: dict,
    player: Player,
    index: AliasIndex,
    league_clubs: list[str],
    min_words: int,
    seen_hashes: set[str],
    source: str = "reddit",
) -> list[TextRecord]:
    raw_body = comment.get("body") or ""
    cleaned = clean_text(raw_body)
    if word_count(cleaned) < min_words:
        return []
    if not is_english(cleaned):
        return []

    # An in-season thread can still collect post-season comments; the window is
    # applied to the unit being kept, not only to its thread (config flag).
    created_utc = float(comment.get("created_utc") or 0)
    if load_config()["text_sources"]["reddit"].get("season_window_only", True):
        season_start, season_end = epoch_window()
        if not (season_start <= created_utc <= season_end):
            return []

    body_hash = text_hash(cleaned)
    if body_hash in seen_hashes:
        return []
    seen_hashes.add(body_hash)

    # A comment in the player's own club subreddit already gives club context.
    club_subs = {s.lower() for s in player_club_subreddits(player)}
    in_club_sub = (comment.get("subreddit") or "").lower() in club_subs

    def resolves(alias: str | None, text: str) -> bool:
        return index.resolves(alias, text, player.player_id, league_clubs, in_club_sub)

    # Whole-comment record: kept only when the comment really names the player.
    alias = index.find_mentions(cleaned, player.player_id)
    if not resolves(alias, cleaned):
        return []

    created = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    thread_id = thread.get("id", "")
    # player_id is part of the id: one comment naming two sample players yields
    # two legitimate records, and text_id is the join key downstream.
    comment_id = f"rd_{comment.get('id') or body_hash}_{player.player_id}"
    shared = dict(
        player_id=player.player_id,
        source=source,
        text_raw=raw_body,
        language="en",
        created_at=created.isoformat(timespec="seconds"),
        url=f"https://www.reddit.com{comment.get('permalink', '')}",
        thread_id=thread_id,
        subreddit=comment.get("subreddit") or thread.get("subreddit", ""),
        engagement=int(comment.get("score") or 0),
    )
    records = [
        TextRecord(
            text_id=comment_id,
            unit_type="comment",
            text_clean=cleaned,
            text_clean_hash=body_hash,
            matched_alias=alias,
            parent_text_id=None,
            **shared,
        )
    ]

    for i, sentence in enumerate(split_sentences(cleaned)):
        sentence_alias = index.find_mentions(sentence, player.player_id)
        if not resolves(sentence_alias, sentence):
            continue
        records.append(
            TextRecord(
                text_id=f"{comment_id}_s{i}",
                unit_type="sentence",
                text_clean=sentence,
                text_clean_hash=text_hash(sentence),
                matched_alias=sentence_alias,
                parent_text_id=comment_id,
                **shared,
            )
        )
    return records


# ---------------------------------------------------------------------- I/O
def write_jsonl(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def unique_raw_dir(tag: str, base: Path | None = None) -> Path:
    """Create a run directory that cannot collide with an earlier run.

    Timestamps are second-resolution, so two runs of the same tag can land in
    the same second; a suffix keeps the older raw output intact (AGENTS.md rule 5).
    """
    root = (base or ROOT / "data" / "raw" / "reddit")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    candidate = root / f"{tag}-{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = root / f"{tag}-{stamp}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def run(players: list[Player], client: RedditClient | None = None, tag: str = "full") -> Path:
    cfg = load_config()["text_sources"]["reddit"]
    if not cfg.get("enabled", False):
        raise SystemExit("reddit source disabled in config/config.yaml - nothing to do")
    client = client or RedditClient()
    index = AliasIndex.build(players)
    league_clubs = load_config()["league"].get("clubs", [])
    quota = int(cfg.get("max_texts_per_player", 60))

    all_records: list[TextRecord] = []
    per_player: dict[str, int] = {}
    for n, player in enumerate(players, start=1):
        records = extract_for_player(client, player, index, league_clubs, quota)
        per_player[player.name] = sum(1 for r in records if r.unit_type == "comment")
        all_records.extend(records)
        log.info("[%d/%d] %-28s %3d comments", n, len(players), player.name, per_player[player.name])

    raw_dir = unique_raw_dir(tag)
    rows = [asdict(r) for r in all_records]
    write_jsonl(rows, raw_dir / "texts.jsonl")

    empty = sorted(name for name, count in per_player.items() if count == 0)
    summary = {
        "run": raw_dir.name,
        "players": len(players),
        "comments": sum(1 for r in all_records if r.unit_type == "comment"),
        "sentences": sum(1 for r in all_records if r.unit_type == "sentence"),
        "requests": client.requests_made,
        "per_player": per_player,
        "players_without_text": empty,
    }
    (raw_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Stable handoff name for the next stages; raw keeps every run.
    interim = ROOT / "data" / "interim" / f"texts_reddit_{tag}.jsonl"
    write_jsonl(rows, interim)
    log.info(
        "kept %d comments / %d sentences from %d requests -> %s (raw: %s)",
        summary["comments"], summary["sentences"], summary["requests"], interim, raw_dir.name,
    )
    if empty:
        log.warning("no texts for %d players: %s", len(empty), ", ".join(empty[:10]))
    return interim
