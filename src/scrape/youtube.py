"""Player-centric YouTube retrieval (Stage B, person C).

Rules enforced here, not in the caller:

  * the player list is the locked text sample; YouTube never invents players
    (AGENTS.md rules 1, 14)
  * retrieval is per player and bounded by the season window from
    `config/config.yaml`, never by literals in this file (rule 13)
  * a comment is kept only when it names the player and, for an ambiguous
    alias, the thread gives the context rule 17 demands
  * `max_texts_per_player` caps volume so stars cannot drown the sample
  * every run logs texts kept per player, so an empty scrape is visible
  * raw output lands in a timestamped run directory and is never overwritten

Two design points that are interpretations, and are recorded as such:

**Video index, not per-player search.** `search.list` costs 100 units and is
banned by AGENTS.md, so candidate videos come from the whitelist channels'
uploads playlists, read once. Walking those per player instead would cost
70 x ~40 pages; read once it is ~40 pages per channel. The population and the
matching decision stay per player.

**Thread context counts as club context.** Reddit gets this for free: a comment
inside r/Gunners is already known to be about Arsenal. A YouTube comment has no
subreddit, so the video itself supplies the context when its title or
description names the player's club, or names the player unambiguously. Without
this, every bare-surname mention ("Saka was clinical") would be dropped and
recall would collapse. The 85% relevance gate (PRD §11) is what measures
whether this is too loose.

Transcripts (`include_transcript: true` in config) are NOT collected here yet.
Do not report transcript coverage from this module.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from src.config import ROOT, load_config
from src.scrape.aliases import AliasIndex
from src.scrape.players import DEFAULT_PLAYERS, Player, load_players, market_values, pilot_subset
from src.scrape.reddit import TextRecord, unique_raw_dir, write_jsonl
from src.scrape.textops import (
    clean_text,
    is_bot_like,
    is_english,
    split_sentences,
    text_hash,
    word_count,
)
from src.scrape.youtube_client import CommentsDisabled, QuotaExceeded, YouTubeClient

log = logging.getLogger("youtube.retrieve")

CHANNELS_CACHE = ROOT / "data" / "raw" / "youtube" / "channels.json"
DEFAULT_MAX_PAGES = 80  # ~4000 uploads; the stop rule usually fires far earlier
MAX_COMMENT_PAGES = 2  # 200 top-level threads per video is plenty for a quota of 40


@dataclass(frozen=True)
class ChannelSource:
    name: str
    channel_id: str
    uploads: str


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    title: str
    description: str
    published_at: str
    channel: str
    matched_on: str = ""  # title | description


@dataclass
class YouTubeTextRecord(TextRecord):
    """Reddit's record shape plus the two fields only YouTube has.

    `subreddit` stays empty so the union with Reddit needs no renaming; `source`
    is what tells the stages apart. Flagged to person D, who consumes the schema.
    """

    channel: str = ""
    video_id: str = ""


# ------------------------------------------------------------------- channels
def _season_window() -> tuple[str, str]:
    league = load_config()["league"]
    return str(league["season_start"]), str(league["season_end"])


def apply_exclusions(players: list[Player]) -> tuple[list[Player], list[dict]]:
    """Drop players whose YouTube matches are known to be a different person.

    The exclusion lives in `config/config.yaml` and carries a written reason, so
    it is visible in the output instead of hidden in a conditional. A rule that
    names a player who is not in the sample is reported: a typo there would
    otherwise exclude nobody and nobody would notice.

    AGENTS.md rule 16 forbids quietly retuning after looking at the results. This
    is the opposite: the reason is recorded, and `docs/decisions.md` carries the
    date and the measured number behind it.
    """
    rules = {
        str(rule["player_id"]): rule
        for rule in (load_config()["text_sources"]["youtube"].get("exclude_players") or [])
        if rule.get("player_id")
    }
    if not rules:
        return list(players), []

    kept: list[Player] = []
    dropped: list[dict] = []
    for player in players:
        rule = rules.get(player.player_id)
        if rule is None:
            kept.append(player)
            continue
        reason = " ".join(str(rule.get("reason") or "no reason given").split())
        dropped.append(
            {"player_id": player.player_id, "name": player.name, "reason": reason}
        )
        log.warning("excluding %s from youtube: %s", player.name, reason)

    unknown = sorted(set(rules) - {player.player_id for player in players})
    if unknown:
        log.warning(
            "exclude_players names %d player_id(s) not in this sample: %s - check for a typo",
            len(unknown),
            ", ".join(unknown),
        )
    return kept, dropped


def _load_channel_cache() -> dict[str, dict]:
    if not CHANNELS_CACHE.exists():
        return {}
    try:
        return json.loads(CHANNELS_CACHE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("corrupt channel cache, rebuilding: %s", CHANNELS_CACHE)
        return {}


def _save_channel_cache(cache: dict[str, dict]) -> None:
    if not cache:
        return
    CHANNELS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHANNELS_CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _title_looks_like(name: str, title: str) -> bool:
    """Loose check that a resolved handle really is the configured channel.

    A wrong handle usually resolves to a fan channel instead of failing
    (verified 2026-11-12: @SkySportsPL is "TRS SkySports"), so silence here is
    how the wrong source gets into the dataset.
    """
    name_tokens = {token for token in name.lower().split() if len(token) > 2}
    title_tokens = {token for token in title.lower().split() if len(token) > 2}
    return bool(name_tokens & title_tokens)


def channel_sources(client: YouTubeClient, *, refresh: bool = False) -> list[ChannelSource]:
    """Resolve the configured channel names to uploads playlists.

    Order of preference: an explicit `uploads`/`channel_id` in config, then the
    local cache of previously resolved handles, then a live `channels.list` call
    for a `handle` in config. Missing information is a hard error, not a silent
    skip: an unresolved channel means missing texts nobody would notice.
    """
    cfg = load_config()["text_sources"]["youtube"]
    entries = cfg.get("channels") or []
    if not entries:
        raise SystemExit("text_sources.youtube.channels is empty in config/config.yaml")

    cache = {} if refresh else _load_channel_cache()
    sources: list[ChannelSource] = []
    changed = False

    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            raise SystemExit(f"channel entry without a name: {entry!r}")

        uploads = str(entry.get("uploads") or "").strip()
        channel_id = str(entry.get("channel_id") or "").strip()

        if not uploads and not channel_id and name in cache:
            uploads = str(cache[name].get("uploads") or "")
            channel_id = str(cache[name].get("channel_id") or "")

        if not uploads and channel_id:
            # YouTube derives the uploads playlist from the channel id (UC.. -> UU..).
            uploads = "UU" + channel_id[2:] if channel_id.startswith("UC") else ""

        if not uploads:
            handle = str(entry.get("handle") or "").strip()
            if not handle:
                raise SystemExit(
                    f"channel {name!r} has no uploads, channel_id, or handle in "
                    "config/config.yaml and is not in the local cache.\n"
                    "Add `handle: @...` to that entry (1 API unit to resolve), or "
                    "resolve it once with `channel_sources(..., refresh=True)`."
                )
            item = client.channel_by_handle(handle)
            if not item:
                raise SystemExit(
                    f"handle {handle} for channel {name!r} does not resolve to any "
                    "channel. A wrong handle is silent otherwise; fix config.yaml."
                )
            title = item["snippet"]["title"]
            if not _title_looks_like(name, title):
                log.warning(
                    "channel %r resolved to %r - titles do not match. Verify this is "
                    "the whitelisted channel, not a fan channel.",
                    name,
                    title,
                )
            channel_id = item["id"]
            uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
            cache[name] = {
                "handle": handle,
                "channel_id": channel_id,
                "uploads": uploads,
                "title": title,
            }
            changed = True

        sources.append(ChannelSource(name=name, channel_id=channel_id, uploads=uploads))

    if changed:
        _save_channel_cache(cache)
    return sources


# ---------------------------------------------------------------------- scan
def scan_channel(
    client: YouTubeClient, source: ChannelSource, *, max_pages: int = DEFAULT_MAX_PAGES
) -> list[VideoCandidate]:
    """In-season videos from one channel's uploads playlist.

    Uploads are newest-first, so the walk stops as soon as a page reaches past
    `season_start`: everything after that is older than the season and cannot be
    relevant. Without that stop rule the walk would run to the channel's first
    video.
    """
    start, end = _season_window()
    videos: list[VideoCandidate] = []
    oldest = ""

    for page in client.iter_playlist_items(source.uploads, max_pages=max_pages):
        items = page.get("items") or []
        if not items:
            break
        for item in items:
            snippet = item.get("snippet") or {}
            published = str(snippet.get("publishedAt") or "")[:10]
            if published:
                oldest = published if not oldest else min(oldest, published)
            if start <= published <= end:
                videos.append(
                    VideoCandidate(
                        video_id=(snippet.get("resourceId") or {}).get("videoId", ""),
                        title=str(snippet.get("title") or ""),
                        description=str(snippet.get("description") or ""),
                        published_at=published,
                        channel=source.name,
                    )
                )
        if oldest and oldest < start:
            break

    log.info(
        "%-28s %4d in-season videos (walked back to %s)",
        source.name,
        len(videos),
        oldest or "?",
    )
    return videos


def match_videos(
    index: AliasIndex, players: list[Player], videos: list[VideoCandidate]
) -> dict[str, list[VideoCandidate]]:
    """Per player, the videos whose title or description names him.

    Title first because it is the stronger signal; the description is scanned
    only when the title misses. Measured 2026-11-12 on three channels: title
    alone covers 47 of 70 sample players, title-or-description covers 59.
    """
    hits: dict[str, list[VideoCandidate]] = defaultdict(list)
    for player in players:
        for video in videos:
            if index.find_mentions(video.title, player.player_id):
                hits[player.player_id].append(replace(video, matched_on="title"))
            elif index.find_mentions(video.description, player.player_id):
                hits[player.player_id].append(replace(video, matched_on="description"))
    return dict(hits)


# ------------------------------------------------------------------- records
def _published_at(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _thread_context(
    index: AliasIndex, video: VideoCandidate, player: Player, league_clubs: list[str]
) -> bool:
    """Does the video itself pin this player down? (rule 17, see module docstring)"""
    blob = f"{video.title} {video.description}"
    if index.has_context(blob, player.player_id, league_clubs):
        return True
    alias = index.find_mentions(video.title, player.player_id)
    return bool(alias) and not index.is_ambiguous(alias)


def records_from_comment(
    comment: dict,
    video: VideoCandidate,
    player: Player,
    index: AliasIndex,
    league_clubs: list[str],
    min_words: int,
    seen_hashes: set[str],
    thread_context: bool,
    counters: dict[str, int] | None = None,
) -> list[YouTubeTextRecord]:
    """One top-level comment -> a comment record plus its sentence records.

    `counters` records why a text was dropped, one bucket per filter, so the
    cleaning table in `reports/cleaning_youtube.md` is produced by the same code
    that does the filtering instead of being written from memory. Passing `None`
    keeps the function usable from tests without bookkeeping.
    """

    def drop(reason: str) -> None:
        if counters is not None:
            counters[f"dropped_{reason}"] = counters.get(f"dropped_{reason}", 0) + 1

    raw_body = str(comment.get("textDisplay") or comment.get("textOriginal") or "")
    cleaned = clean_text(raw_body)
    if word_count(cleaned) < min_words:
        drop("too_short")
        return []
    if not is_english(cleaned):
        drop("not_english")
        return []
    if is_bot_like("", cleaned):
        drop("bot_like")
        return []

    created = _published_at(str(comment.get("publishedAt") or ""))
    if created is None:
        drop("no_date")
        return []
    start, end = _season_window()
    if not (start <= created.date().isoformat() <= end):
        drop("outside_season")
        return []

    body_hash = text_hash(cleaned)
    if body_hash in seen_hashes:
        drop("duplicate")
        return []
    seen_hashes.add(body_hash)

    alias = index.find_mentions(cleaned, player.player_id)
    if not index.resolves(alias, cleaned, player.player_id, league_clubs, thread_context):
        drop("name_not_resolved")
        return []

    comment_id = str(comment.get("id") or body_hash)
    text_id = f"yt_{comment_id}_{player.player_id}"
    shared = dict(
        player_id=player.player_id,
        source="youtube",
        text_raw=raw_body,
        language="en",
        created_at=created.astimezone(timezone.utc).isoformat(timespec="seconds"),
        url=f"https://www.youtube.com/watch?v={video.video_id}&lc={comment_id}",
        thread_id=video.video_id,
        subreddit="",  # no subreddit on YouTube; `channel` carries the source
        engagement=int(comment.get("likeCount") or 0),
        matched_alias=str(alias),
        channel=video.channel,
        video_id=video.video_id,
    )

    records = [
        YouTubeTextRecord(
            text_id=text_id,
            unit_type="comment",
            text_clean=cleaned,
            text_clean_hash=body_hash,
            parent_text_id=None,
            **shared,
        )
    ]
    for position, sentence in enumerate(split_sentences(cleaned)):
        sentence_alias = index.find_mentions(sentence, player.player_id)
        if not index.resolves(
            sentence_alias, sentence, player.player_id, league_clubs, thread_context
        ):
            drop("sentence_not_resolved")
            continue
        records.append(
            YouTubeTextRecord(
                text_id=f"{text_id}_s{position}",
                unit_type="sentence",
                text_clean=sentence,
                text_clean_hash=text_hash(sentence),
                parent_text_id=text_id,
                **{**shared, "matched_alias": str(sentence_alias)},
            )
        )
    return records


def extract_for_player(
    client: YouTubeClient,
    player: Player,
    videos: list[VideoCandidate],
    index: AliasIndex,
    league_clubs: list[str],
    quota: int,
    min_words: int,
    counters: dict[str, int] | None = None,
) -> list[YouTubeTextRecord]:
    counters = counters if counters is not None else {}
    records: list[YouTubeTextRecord] = []
    seen_hashes: set[str] = set()
    # `max_texts_per_player` caps COMMENTS. Counting sentences against the same
    # budget halved the yield: 20 comments plus their 20 sentences reached the
    # cap of 40, so no player ever got the 40 comments the config promises.
    kept_comments = 0

    for video in videos:
        if kept_comments >= quota:
            break
        context = _thread_context(index, video, player, league_clubs)
        try:
            pages = client.iter_comment_threads(video.video_id, max_pages=MAX_COMMENT_PAGES)
            for page in pages:
                for thread in page.get("items") or []:
                    if kept_comments >= quota:
                        break
                    top = ((thread.get("snippet") or {}).get("topLevelComment") or {}).get("snippet")
                    if not top:
                        continue
                    counters["comments_examined"] = counters.get("comments_examined", 0) + 1
                    added = records_from_comment(
                        top,
                        video,
                        player,
                        index,
                        league_clubs,
                        min_words,
                        seen_hashes,
                        context,
                        counters,
                    )
                    records.extend(added)
                    kept_comments += sum(1 for r in added if r.unit_type == "comment")
        except CommentsDisabled:
            counters["comments_disabled"] = counters.get("comments_disabled", 0) + 1
            log.debug("comments disabled: %s (%s)", video.video_id, video.title[:50])
        except QuotaExceeded:
            raise
        except Exception as exc:  # one bad video must not kill the run
            counters["video_errors"] = counters.get("video_errors", 0) + 1
            log.warning("video %s failed: %s", video.video_id, exc)

    return [record for record in records if record.unit_type == "comment"][:quota] + [
        record for record in records if record.unit_type == "sentence"
    ]


# ------------------------------------------------------------------------ run
def run(
    players: list[Player], client: YouTubeClient | None = None, tag: str = "full"
) -> Path:
    cfg = load_config()["text_sources"]["youtube"]
    if not cfg.get("enabled", False):
        raise SystemExit("youtube source disabled in config/config.yaml - nothing to do")

    client = client or YouTubeClient()
    players, excluded = apply_exclusions(players)
    if not players:
        raise SystemExit("every player was excluded for youtube - nothing to collect")
    index = AliasIndex.build(players)
    league_clubs = list(load_config()["league"].get("clubs", []))
    quota = int(cfg.get("max_texts_per_player", 40))
    min_words = int(cfg.get("min_words", 8))

    sources = channel_sources(client)
    videos: list[VideoCandidate] = []
    for source in sources:
        videos.extend(scan_channel(client, source))
    log.info("in-season candidate videos: %d from %d channels", len(videos), len(sources))

    matches = match_videos(index, players, videos)
    log.info(
        "players with at least one candidate video: %d/%d",
        len(matches),
        len(players),
    )

    counters: dict[str, int] = {}
    all_records: list[YouTubeTextRecord] = []
    per_player: dict[str, int] = {}
    for position, player in enumerate(players, start=1):
        records = extract_for_player(
            client,
            player,
            matches.get(player.player_id, []),
            index,
            league_clubs,
            quota,
            min_words,
            counters,
        )
        kept = sum(1 for record in records if record.unit_type == "comment")
        per_player[player.name] = kept
        all_records.extend(records)
        log.info("[%d/%d] %-28s %3d comments", position, len(players), player.name, kept)

    raw_dir = unique_raw_dir(tag, base=ROOT / "data" / "raw" / "youtube")
    rows = [asdict(record) for record in all_records]
    write_jsonl(rows, raw_dir / "texts.jsonl")

    empty = sorted(name for name, count in per_player.items() if count == 0)
    summary = {
        "run": raw_dir.name,
        "source": "youtube",
        "players": len(players),
        "channels": [source.name for source in sources],
        "videos_scanned": len(videos),
        "videos_matched": sum(len(v) for v in matches.values()),
        "players_with_candidate_video": len(matches),
        "comments": sum(1 for r in all_records if r.unit_type == "comment"),
        "sentences": sum(1 for r in all_records if r.unit_type == "sentence"),
        "requests": client.network_requests,
        "quota_units": client.quota_units,
        "cache_hits": client.cache_hits,
        "comments_disabled_videos": counters.get("comments_disabled", 0),
        "video_errors": counters.get("video_errors", 0),
        "filters": {
            "comments_examined": counters.get("comments_examined", 0),
            "comments_kept": sum(1 for r in all_records if r.unit_type == "comment"),
            "sentences_kept": sum(1 for r in all_records if r.unit_type == "sentence"),
            "dropped": {
                key.removeprefix("dropped_"): value
                for key, value in sorted(counters.items())
                if key.startswith("dropped_")
            },
        },
        "per_player": per_player,
        "players_without_text": empty,
        "excluded_players": excluded,
    }
    (raw_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    interim = ROOT / "data" / "interim" / f"texts_youtube_{tag}.jsonl"
    write_jsonl(rows, interim)
    log.info(
        "kept %d comments / %d sentences from %d requests (%d quota units) -> %s",
        summary["comments"],
        summary["sentences"],
        summary["requests"],
        summary["quota_units"],
        interim,
    )
    if empty:
        log.warning("no texts for %d players: %s", len(empty), ", ".join(empty[:10]))
    return interim


# ------------------------------------------------------------------------ CLI
def _sample_players(path: Path | None = None) -> list[Player]:
    """The locked sample, with the same hard stop `run.py` applies (rule 14)."""
    target = Path(path) if path else DEFAULT_PLAYERS
    if not target.exists():
        raise SystemExit(
            f"locked text sample not found: {target}\n"
            "Stage A (person A) locks data/processed/text_sample.parquet on Day 1; "
            "Stage B must not pick its own players."
        )
    if path is None and not load_config()["text_sample"].get("locked"):
        raise SystemExit(
            "text_sample.locked is false in config/config.yaml - the sample is not "
            "frozen yet, so scraping now would not be reproducible."
        )
    return load_players(target)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point, so pilots do not need the shared `run.py`.

    `python -m src.scrape.youtube --pilot 5` is the Day-2 gate. The full run is
    wired into `src/scrape/run.py --provider youtube` once the team agrees on the
    shared CLI shape.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Stage B: player-centric YouTube retrieval")
    parser.add_argument("--pilot", type=int, metavar="N", help="run on N players spread by market value")
    parser.add_argument("--players", help=f"population file (default {DEFAULT_PLAYERS.name})")
    parser.add_argument("--tag", help="run tag; defaults to pilot<N> or full")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    players = _sample_players(args.players)
    if args.pilot:
        players = pilot_subset(players, args.pilot, market_values(args.players or DEFAULT_PLAYERS))
    tag = args.tag or (f"pilot{args.pilot}" if args.pilot else "full")
    log.info("youtube run: %d players, tag=%s", len(players), tag)
    run(players, tag=tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
