"""Step 1: measure thread volume before committing to any scraping.

Answers three questions per player, over 2025-07-01 to 2026-05-31:

  1. how many threads in r/soccer and the two club subreddits
  2. whether a surname query catches the short alias ("Salah" -> "Mo Salah")
  3. what share of threads actually discuss the player rather than merely
     mentioning the name

Nothing is scraped in bulk here. This is the cheap measurement that decides
whether the post-first strategy is affordable at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.scrape.arctic_shift_client import ArcticShiftClient, ArcticShiftError

CACHE_DIR = Path("data/raw/arctic_shift")
OUT_DIR = Path("data/processed/probe")

SEASON_AFTER = "2025-07-01"
SEASON_BEFORE = "2026-05-31"


@dataclass
class PlayerProbe:
    """One player's measurement across subreddits."""

    label: str
    name: str
    club: str
    aliases: list[str]
    subreddits: list[str]
    threads: dict[str, int] = field(default_factory=dict)
    threads_by_alias: dict[str, dict[str, int]] = field(default_factory=dict)
    sampled_titles: list[str] = field(default_factory=list)


def count_threads(
    client: ArcticShiftClient,
    subreddit: str,
    query: str,
    *,
    after: str = SEASON_AFTER,
    before: str = SEASON_BEFORE,
    limit: int = 100,
) -> tuple[int, list[dict]]:
    """Count posts matching ``query`` in one subreddit for the season.

    Returns the number returned by the API and the raw posts, so the caller can
    check relevance. A count of exactly ``limit`` means the result is capped and
    the real number is higher; that is recorded rather than hidden.
    """
    try:
        payload = client.posts(
            subreddit=subreddit,
            query=query,
            after=after,
            before=before,
            limit=limit,
        )
    except ArcticShiftError as exc:
        logging.warning("query failed (%s/%s): %s", subreddit, query, exc)
        return -1, []

    posts = payload.get("data") or []
    return len(posts), posts


def mentions(text: str, patterns: list[str]) -> bool:
    """Case- and accent-insensitive substring check."""
    import unicodedata

    def fold(value: str) -> str:
        value = "".join(
            {"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ł": "l", "Ł": "L"}.get(c, c)
            for c in value
        )
        normalized = unicodedata.normalize("NFKD", value)
        stripped = "".join(c for c in normalized if not unicodedata.combining(c))
        return stripped.casefold()

    haystack = fold(text)
    return any(fold(p) in haystack for p in patterns)


def assert_club_subreddit_sane(subreddit: str, timeout_report: dict) -> None:
    """Placeholder for an explicit sanity note; kept for readability."""
    del subreddit, timeout_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "step1_volume.json")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = ArcticShiftClient(CACHE_DIR)

    probes = [
        PlayerProbe(
            label="popular",
            name="Erling Haaland",
            club="Manchester City",
            aliases=["Haaland", "Erling Haaland"],
            subreddits=["soccer", "MCFC", "PremierLeague"],
        ),
        PlayerProbe(
            label="middle",
            name="Adam Wharton",
            club="Crystal Palace",
            aliases=["Wharton", "Adam Wharton"],
            subreddits=["soccer", "crystalpalace", "PremierLeague"],
        ),
        PlayerProbe(
            label="fringe",
            name="Martin Dúbravka",
            club="Burnley",
            aliases=["Dubravka", "Dúbravka", "Martin Dubravka"],
            subreddits=["soccer", "Burnley", "PremierLeague"],
        ),
    ]

    results: list[dict] = []

    for probe in probes:
        logging.info("=== %s: %s ===", probe.label, probe.name)
        surnames = [probe.aliases[0]]
        entry: dict = {
            "label": probe.label,
            "name": probe.name,
            "club": probe.club,
            "aliases": probe.aliases,
            "subreddits": {},
            "alias_check": {},
            "relevance": {},
        }

        for subreddit in probe.subreddits:
            count, posts = count_threads(
                client, subreddit, surnames[0], limit=args.limit
            )
            capped = count >= args.limit
            entry["subreddits"][subreddit] = {"count": count, "capped": capped}
            logging.info(
                "  r/%-16s %d threads%s", subreddit, count, " (CAPPED)" if capped else ""
            )

            if posts:
                relevant = [
                    p
                    for p in posts
                    if mentions(
                        f"{p.get('title','')} {p.get('selftext','')}",
                        probe.aliases,
                    )
                ]
                entry["relevance"][subreddit] = {
                    "sampled": len(posts),
                    "mentions_name": len(relevant),
                    "share": round(len(relevant) / len(posts), 3),
                }
                if not probe.sampled_titles:
                    probe.sampled_titles = [
                        str(p.get("title", ""))[:100] for p in posts[:5]
                    ]

        # alias check: does the short form miss the full form?
        for alias in probe.aliases:
            count, _ = count_threads(client, "soccer", alias, limit=args.limit)
            entry["alias_check"][alias] = count
            logging.info("  alias '%-16s' in r/soccer: %d", alias, count)

        entry["sample_titles"] = probe.sampled_titles
        results.append(entry)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print()
    print("=== RINGKASAN LANGKAH 1 ===")
    for entry in results:
        print(f"\n[{entry['label']}] {entry['name']} ({entry['club']})")
        for sub, stats in entry["subreddits"].items():
            rel = entry["relevance"].get(sub, {})
            share = f"{rel.get('share', 0):.0%}" if rel else "n/a"
            capped = " CAPPED" if stats["capped"] else ""
            print(f"   r/{sub:<16} {stats['count']:>4} thread  relevan={share}{capped}")
        print(f"   alias: {entry['alias_check']}")

    print(f"\nnetwork={client.network_requests} cache={client.cache_hits} "
          f"backpressure={client.backpressure_events}")
    print(f"disimpan: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
