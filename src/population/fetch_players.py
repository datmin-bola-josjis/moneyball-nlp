"""Fetch one FotMob ``playerData`` payload per player in the population.

Run once to populate ``data/raw/fotmob/players/``. The client caches to disk,
so rerunning only fetches what is missing and the job is safe to interrupt.

Usage:
    python3 -m src.population.fetch_players
    python3 -m src.population.fetch_players --minutes-file path.json --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.scrape.fotmob_client import FotMobClient, FotMobError

RAW_DIR = Path("data/raw/fotmob")
PLAYER_CACHE = RAW_DIR / "players"
DEFAULT_MINUTES = RAW_DIR / "mins_played.json"
MIN_MINUTES_FALLBACK = 900


def load_population_ids(
    minutes_file: Path, *, min_minutes: int = MIN_MINUTES_FALLBACK
) -> list[int]:
    """Return FotMob player ids that clear the minutes threshold."""
    payload = json.loads(minutes_file.read_text(encoding="utf-8"))
    ids: list[int] = []
    for row in payload["statsData"]:
        value = (row.get("statValue") or {}).get("value")
        if isinstance(value, (int, float)) and value >= min_minutes:
            ids.append(int(row["id"]))
    return ids


def fetch_all(
    player_ids: list[int],
    *,
    cache_dir: Path,
    min_interval: float = 1.0,
    limit: int | None = None,
) -> tuple[int, int, list[int]]:
    """Fetch each player, returning (fetched, cached, failed_ids)."""
    client = FotMobClient(cache_dir, min_interval=min_interval)
    targets = player_ids[:limit] if limit else player_ids
    failed: list[int] = []

    for index, player_id in enumerate(targets, start=1):
        try:
            client.player(player_id)
        except FotMobError as exc:
            logging.warning("player %s failed: %s", player_id, exc)
            failed.append(player_id)
        if index % 25 == 0 or index == len(targets):
            logging.info(
                "%d/%d done (network=%d cached=%d failed=%d)",
                index,
                len(targets),
                client.network_requests,
                client.cache_hits,
                len(failed),
            )

    return client.network_requests, client.cache_hits, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes-file", type=Path, default=DEFAULT_MINUTES)
    parser.add_argument("--min-minutes", type=int, default=MIN_MINUTES_FALLBACK)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=1.0,
        help="seconds between requests; must be >= 1.0",
    )
    parser.add_argument("--limit", type=int, default=None, help="fetch only N players")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if not args.minutes_file.exists():
        logging.error("minutes file not found: %s", args.minutes_file)
        return 2

    player_ids = load_population_ids(args.minutes_file, min_minutes=args.min_minutes)
    logging.info("population after minutes filter: %d players", len(player_ids))

    fetched, cached, failed = fetch_all(
        player_ids,
        cache_dir=PLAYER_CACHE,
        min_interval=args.min_interval,
        limit=args.limit,
    )

    logging.info(
        "finished: network=%d cached=%d failed=%d", fetched, cached, len(failed)
    )
    if failed:
        logging.error("failed ids: %s", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
