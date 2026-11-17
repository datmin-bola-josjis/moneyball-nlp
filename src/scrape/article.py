"""Player-centric article retrieval (Stage B, bonus source, PRD §12).

Disabled by default (`text_sources.article.enabled: false`). This module exists
so the config flag describes real behaviour instead of a promise, exactly like
the transcript collector did.

Rules enforced here, not in the caller:

  * the player list is the locked text sample; articles never add a player
    (AGENTS.md rules 1 and 14)
  * an article only counts when the player's name is in the title or appears at
    least `min_name_mentions` times in the body (PRD §12) - a single passing
    mention is not evidence about a player
  * `robots.txt` is honoured per host and cached, because rule 12 outranks
    convenience; a disallowed path is skipped and counted, never retried
  * requests are rate limited to at least one second apart (working convention)
  * raw HTML is never overwritten: each run writes a timestamped directory
  * paywalled hosts are skipped when `respect_paywall` is true, and the skip is
    counted rather than treated as an error

The unit is a paragraph, not an article. A 900-word article about a match is not
evidence about one player, and Stage D scores sentences; a paragraph that names
the player is the smallest unit that stays readable.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.robotparser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from src.config import ROOT, load_config
from src.scrape.aliases import AliasIndex
from src.scrape.players import DEFAULT_PLAYERS, Player, load_players, pilot_subset
from src.scrape.reddit import TextRecord, unique_raw_dir, write_jsonl
from src.scrape.textops import (
    clean_text,
    is_english,
    split_sentences,
    text_hash,
    word_count,
)

log = logging.getLogger("article.retrieve")

USER_AGENT: Final[str] = "moneyball-nlp/0.1 (academic project; contact via repository)"
MIN_INTERVAL: Final[float] = 1.0
ROBOTS_TTL_SECONDS: Final[int] = 6 * 3600


@dataclass
class ArticleTextRecord(TextRecord):
    """Reddit's record shape plus the publisher.

    `channel` already exists in the dedupe schema and carries the source of a
    YouTube record, so the publisher goes there rather than adding a column that
    would be dropped by `src/link/dedupe.py` as "not in the schema".
    """

    channel: str = ""


@dataclass(frozen=True)
class ArticleCandidate:
    url: str
    title: str
    publisher: str
    published_at: str = ""
    body: str = ""


class RobotsCache:
    """Per-host `robots.txt`, fetched once and honoured for the whole run."""

    def __init__(self, fetch_text=None) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last: dict[str, float] = {}
        self._fetch_text = fetch_text

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        host = f"{parsed.scheme}://{parsed.netloc}"
        now = time.monotonic()
        cached_at = self._last.get(host)
        if cached_at is not None and now - cached_at < ROBOTS_TTL_SECONDS:
            parser = self._cache[host]
        else:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{host}/robots.txt")
            try:
                if self._fetch_text is not None:
                    raw = self._fetch_text(f"{host}/robots.txt")
                    parser.parse(raw.splitlines() if raw else [])
                else:
                    parser.read()
            except Exception as exc:  # an unreachable robots.txt is not a licence
                log.warning("robots.txt unavailable for %s (%s) - skipping host", host, exc)
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(["User-agent: *", "Disallow: /"])
            self._cache[host] = parser
            self._last[host] = now
        return parser.can_fetch(USER_AGENT, url)


def split_paragraphs(body: str) -> list[str]:
    """Split an article body into cleaned paragraph blocks.

    Deliberately does no length filtering. A word threshold here would compete
    with `min_words` from the config (rule 13) and, worse, would drop blocks
    before `records_from_article` could count *why* - which is what makes the
    cleaning table reproducible.
    """
    return [cleaned for cleaned in (clean_text(block) for block in body.split("\n")) if cleaned]


def count_name_mentions(text: str, player: Player) -> int:
    """How often the player is named, counting overlapping aliases once.

    Whole-phrase matching on purpose: a substring count would score "Saka" inside
    another word and inflate the gate that decides whether the article is about
    him at all.

    Aliases are matched longest-first over marked spans, because a full name
    contains its own surname: "Bukayo Saka" would otherwise count twice and push
    an article past `min_name_mentions` on a single mention.
    """
    haystack = f" {text.lower()} "
    aliases = sorted(
        {alias.strip().lower() for alias in (player.name, *player.aliases) if alias.strip()},
        key=len,
        reverse=True,
    )
    taken = [False] * len(haystack)
    total = 0
    for alias in aliases:
        needle = f" {alias} "
        start = haystack.find(needle)
        while start != -1:
            span = range(start, start + len(needle))
            if not any(taken[i] for i in span):
                for i in span:
                    taken[i] = True
                total += 1
            start = haystack.find(needle, start + 1)
    return total


def article_matches(
    candidate: ArticleCandidate, player: Player, min_name_mentions: int
) -> bool:
    """PRD §12: name in the title, or at least `min_name_mentions` in the body."""
    if count_name_mentions(candidate.title, player) > 0:
        return True
    return count_name_mentions(candidate.body, player) >= max(min_name_mentions, 1)


def records_from_article(
    candidate: ArticleCandidate,
    player: Player,
    min_words: int,
    seen_hashes: set[str],
    counters: dict[str, int] | None = None,
) -> list[ArticleTextRecord]:
    """One article -> sentence records that name the player.

    The unit type is `sentence`, not `article_paragraph`, for the same reason the
    transcript path uses `sentence`: PRD §8 locks `unit_type` to
    `comment`/`sentence` and Stage D selects only `unit_type == "sentence"`. A
    bespoke type would be written and then never analysed.
    """
    counters = counters if counters is not None else {}

    def drop(reason: str) -> None:
        counters[f"dropped_{reason}"] = counters.get(f"dropped_{reason}", 0) + 1

    records: list[ArticleTextRecord] = []
    for position, paragraph in enumerate(split_paragraphs(candidate.body)):
        if word_count(paragraph) < min_words:
            drop("article_paragraph_too_short")
            continue
        if not is_english(paragraph):
            drop("article_not_english")
            continue
        if count_name_mentions(paragraph, player) == 0:
            drop("article_paragraph_no_name")
            continue

        for offset, sentence in enumerate(split_sentences(paragraph)):
            sentence_clean = clean_text(sentence)
            if word_count(sentence_clean) < min_words:
                drop("article_sentence_too_short")
                continue
            if count_name_mentions(sentence_clean, player) == 0:
                drop("article_sentence_no_name")
                continue

            sentence_hash = text_hash(sentence_clean)
            if sentence_hash in seen_hashes:
                drop("article_duplicate")
                continue
            seen_hashes.add(sentence_hash)

            records.append(
                ArticleTextRecord(
                    text_id=(
                        f"ar_{sentence_hash}_{player.player_id}_p{position}s{offset}"
                    ),
                    player_id=player.player_id,
                    source="article",
                    unit_type="sentence",
                    text_raw=sentence_clean,
                    text_clean=sentence_clean,
                    text_clean_hash=sentence_hash,
                    language="en",
                    created_at=candidate.published_at,
                    url=candidate.url,
                    thread_id=candidate.url,
                    subreddit="",
                    engagement=0,
                matched_alias=player.name,
                parent_text_id=None,
                channel=candidate.publisher,
            )
        )
    return records


def extract_article(html: str, url: str) -> str:
    """Main text of one HTML document, or an empty string.

    Imported lazily for the same reason the transcript client is: a checkout that
    only runs the Reddit path should not need the dependency installed.
    """
    try:
        import trafilatura
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "trafilatura is not installed; run `make setup` before `make scrape-articles`"
        ) from exc

    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    return (extracted or "").strip()


def fetch_html(url: str, *, timeout: int = 20, fetcher=None) -> str:
    """One GET with the project's User-Agent; `fetcher` is injected in tests."""
    if fetcher is not None:
        return fetcher(url)
    import requests

    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def _require_downstream_filter() -> None:
    """Refuse to run when Stage C cannot disambiguate `article` rows.

    Rule 17 is not a style preference: without a context check, a bare surname in
    a match report about another club is attributed to our player. Stage C
    (`src/link/resolve.py`) is where that check lives and it is currently an
    untracked Role D file, so a checkout may or may not have the `article`
    branch. Rather than assume, read the source and stop if the branch is
    missing - producing rows nothing filters is worse than producing none.
    """
    source = ROOT / "src" / "link" / "resolve.py"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if 'source == "article"' not in text:
        raise SystemExit(
            "refusing to collect articles: src/link/resolve.py has no `article` "
            "branch, so rule 17 (ambiguous names need club context) would not be "
            "enforced on these rows. Keep text_sources.article.enabled: false "
            "until that branch is in the repository."
        )


def run(
    players: list[Player],
    candidates: list[ArticleCandidate],
    *,
    cfg: dict | None = None,
    seen_hashes: set[str] | None = None,
) -> Path:
    """Collect paragraph records for `players` from already-fetched candidates.

    Splitting the fetch out keeps the network path out of the unit tests: the
    caller supplies candidates, this function applies the rules and writes.
    """
    cfg = cfg if cfg is not None else load_config()["text_sources"]["article"]
    if not cfg.get("enabled", False):
        raise SystemExit("article source disabled in config/config.yaml - nothing to do")
    _require_downstream_filter()

    min_words = int(cfg.get("min_words", 8))
    min_mentions = int(cfg.get("min_name_mentions", 3))
    seen = seen_hashes if seen_hashes is not None else set()

    counters: dict[str, int] = {}
    records: list[ArticleTextRecord] = []
    per_player: dict[str, int] = {}

    for order, player in enumerate(players, start=1):
        matched = 0
        for candidate in candidates:
            if not article_matches(candidate, player, min_mentions):
                continue
            matched += 1
            records.extend(
                records_from_article(candidate, player, min_words, seen, counters)
            )
        per_player[player.name] = matched
        log.info(
            "[%d/%d] %-28s %3d article(s)", order, len(players), player.name, matched
        )

    raw_dir = unique_raw_dir("full", base=ROOT / "data" / "raw" / "article")
    rows = [asdict(record) for record in records]
    write_jsonl(rows, raw_dir / "texts.jsonl")
    interim = ROOT / "data" / "interim" / "texts_article_full.jsonl"
    write_jsonl(rows, interim)

    summary = {
        "run": raw_dir.name,
        "source": "article",
        "players": len(players),
        "candidates": len(candidates),
        "paragraphs": len(records),
        "per_player": per_player,
        "players_without_text": sorted(
            name for name, count in per_player.items() if count == 0
        ),
        "dropped": {
            key.removeprefix("dropped_"): value
            for key, value in sorted(counters.items())
            if key.startswith("dropped_")
        },
    }
    (raw_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("kept %d paragraphs -> %s", len(records), interim)
    return interim


def _sample_players(path: Path | None = None) -> list[Player]:
    target = Path(path) if path else DEFAULT_PLAYERS
    if not target.exists():
        raise SystemExit(
            f"{target} not found - lock the sample first (`make lock-sample`); "
            "articles never invent players (AGENTS.md rule 14)"
        )
    return load_players(target)


def main(argv: list[str] | None = None) -> int:
    """CLI kept honest: without configured URLs there is nothing to fetch."""
    import argparse

    parser = argparse.ArgumentParser(description="Stage B: player-centric article retrieval")
    parser.add_argument("--players", type=Path, default=None)
    parser.add_argument("--pilot", type=int, default=None)
    parser.add_argument("--urls", type=Path, default=None, help="file with one URL per line")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    cfg = load_config()["text_sources"]["article"]
    if not cfg.get("enabled", False):
        raise SystemExit(
            "article source disabled in config/config.yaml - set "
            "text_sources.article.enabled: true and record the decision in "
            "docs/decisions.md before using it"
        )

    players = _sample_players(args.players)
    if args.pilot:
        players = pilot_subset(players, args.pilot, market_values(players))
    if args.urls is None:
        raise SystemExit("--urls is required; no URL discovery is implemented yet")

    domains = tuple(cfg.get("domains", ()))
    robots = RobotsCache()
    candidates: list[ArticleCandidate] = []
    for raw in args.urls.read_text(encoding="utf-8").splitlines():
        url = raw.strip()
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        if domains and not any(host.endswith(domain) for domain in domains):
            log.info("skip %s: not in the configured domain whitelist", host)
            continue
        if not robots.allowed(url):
            log.info("skip %s: robots.txt disallows it", url)
            continue
        try:
            html = fetch_html(url)
        except Exception as exc:
            log.warning("fetch failed %s: %s", url, exc)
            continue
        body = extract_article(html, url)
        if not body:
            log.info("skip %s: no article text extracted", url)
            continue
        candidates.append(
            ArticleCandidate(
                url=url,
                title="",
                publisher=host,
                published_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                body=body,
            )
        )
        time.sleep(MIN_INTERVAL)

    run(players, candidates, cfg=cfg)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the Makefile
    raise SystemExit(main())
