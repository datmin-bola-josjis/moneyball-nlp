"""Build ``metrics_numeric``: ratings, per-90 performance, positional z-scores.

Run after the population exists and after the stat payloads are cached.

Order is deliberate: join, then gate, then write. A metrics table that fails
its own checks must not reach disk, because every downstream candidate claim
depends on it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yaml

from src.score.metrics import (
    KNOWN_COVERAGE_LIMITS,
    OUT_METRICS,
    build_metrics,
    rating_zscore_within_position,
    validate_metrics,
)

logger = logging.getLogger(__name__)

POPULATION = Path("data/processed/players.parquet")
CONFIG_PATH = Path("config/config.yaml")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not POPULATION.exists():
        logger.error("population missing: %s (run `make population`)", POPULATION)
        return 1

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    min_minutes = int((config.get("population") or {}).get("min_minutes", 900))
    min_for_rating = int(
        (config.get("validation") or {}).get("min_minutes_for_rating", 900)
    )

    population = pd.read_parquet(POPULATION)
    frame = build_metrics(population)

    frame["rating_pos_zscore"] = rating_zscore_within_position(
        frame, min_minutes=min_for_rating
    )

    coverage = {
        column: int(frame[column].notna().sum())
        for column in (
            "avg_rating",
            "xg_per90",
            "xa_per90",
            "tackles_per90",
            "interceptions_per90",
        )
    }
    logger.info("coverage: %s", coverage)
    for stat, note in KNOWN_COVERAGE_LIMITS.items():
        logger.info("known limit for %s: %s", stat, note)

    problems = validate_metrics(frame)
    if problems:
        logger.error("metrics gate FAILED, nothing written:")
        for problem in problems:
            logger.error("  - %s", problem)
        return 1

    values_present = int(frame["market_value_eur"].notna().sum())
    logger.info(
        "minutes threshold %d, rating threshold %d, prices %d/%d",
        min_minutes,
        min_for_rating,
        values_present,
        len(frame),
    )

    OUT_METRICS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT_METRICS, index=False)
    logger.info("wrote %d rows to %s", len(frame), OUT_METRICS)

    zscore_covered = int(frame["rating_pos_zscore"].notna().sum())
    logger.info("rating z-score available for %d players", zscore_covered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
