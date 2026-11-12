"""Build the population, sample the text path, and lock the sample file.

Run order matters and is enforced here rather than left to whoever runs it:

1. read the cached player payloads (``fetch_players`` must have run)
2. build ``data/processed/players.parquet``
3. sample the text path with stratification
4. run the gate in :func:`src.population.sampling.verify_sample`
5. only then write ``text_sample.parquet`` and flip ``locked`` in config

If the gate reports a problem, nothing is written and the exit code is 1. A
locked sample is a methodological guarantee (docs/PRD.md section 7.A.5), so it
must not be produced by a run that failed its own checks.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from src.population.build import (
    OUT_PLAYERS,
    drop_colliding_aliases,
    load_population,
    to_dataframe,
)
from src.population.sampling import (
    SampleConfig,
    assign_price_quartiles,
    stratified_sample,
    verify_population,
    verify_sample,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/config.yaml")
SAMPLE_LOCKED = Path("data/processed/text_sample.parquet")
SAMPLE_REVIEW = Path("data/processed/text_sample_review.csv")


def sample_config_from(config: dict) -> SampleConfig:
    block = config.get("text_sample") or {}
    return SampleConfig(
        target_players=int(block.get("target_players", 70)),
        per_position_group=int(block.get("per_position_group", 17)),
        min_per_cell=int(block.get("min_per_cell", 4)),
        random_seed=int(block.get("random_seed", 20252026)),
    )


def report_census(sample: pd.DataFrame) -> str:
    """Readable per-cell summary, printed before locking."""
    counts = (
        sample.groupby(["position_group", "price_quartile"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=["GK", "DEF", "MID", "FWD"], columns=["Q1", "Q2", "Q3", "Q4"], fill_value=0)
    )
    lines = ["cell census (selected players):", counts.to_string()]
    lines.append("")
    lines.append("per position group: " + str(
        sample["position_group"].value_counts().sort_index().to_dict()
    ))
    lines.append(f"total selected: {len(sample)}")
    return "\n".join(lines)


def main(*, lock: bool = False, allow_partial: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = sample_config_from(config)
    min_minutes = int((config.get("population") or {}).get("min_minutes", 900))

    club_aliases = (config.get("league") or {}).get("club_name_aliases") or {}
    records, missing = load_population(
        min_minutes=min_minutes, club_aliases=club_aliases
    )
    if missing and not allow_partial:
        logger.error(
            "%d players lack a cached payload; run `make fetch-players` first "
            "(or pass --allow-partial for a dry run). Missing: %s",
            len(missing),
            missing[:10],
        )
        return 1
    if missing:
        logger.warning("proceeding with %d players missing payloads", len(missing))

    collisions = drop_colliding_aliases(records)
    if collisions:
        logger.warning("dropped %d ambiguous aliases", len(collisions))

    population = to_dataframe(records)

    expected_clubs = (config.get("league") or {}).get("clubs") or []
    population_problems = verify_population(population, expected_clubs)
    if population_problems:
        logger.error("population gate FAILED, nothing written:")
        for problem in population_problems:
            logger.error("  - %s", problem)
        return 1
    logger.info("population gate passed: %d players, 20 clubs", len(population))

    OUT_PLAYERS.parent.mkdir(parents=True, exist_ok=True)
    population.to_parquet(OUT_PLAYERS, index=False)
    logger.info("wrote %d players to %s", len(population), OUT_PLAYERS)

    priced = int(population["market_value_eur"].notna().sum())
    logger.info("market value present for %d/%d players", priced, len(population))
    if priced == 0:
        logger.error("no market values at all; sampling cannot stratify by price")
        return 1

    population = population.assign(
        price_quartile=assign_price_quartiles(population)
    )
    population["stratum"] = (
        population["position_group"] + "_" + population["price_quartile"]
    )

    sample = stratified_sample(population, cfg)
    print(report_census(sample))

    problems = verify_sample(
        sample.assign(selected=1) if "selected" not in sample else sample,
        population,
        cfg,
    )
    if problems:
        logger.error("sample gate FAILED, nothing written:")
        for problem in problems:
            logger.error("  - %s", problem)
        return 1

    logger.info("sample gate passed")

    SAMPLE_REVIEW.parent.mkdir(parents=True, exist_ok=True)
    review_columns = [
        "player_id",
        "name_canonical",
        "name_aliases",
        "club",
        "position",
        "position_group",
        "price_quartile",
        "market_value_eur",
        "minutes",
    ]
    sample[review_columns].to_csv(SAMPLE_REVIEW, index=False)
    logger.info("wrote review file to %s", SAMPLE_REVIEW)

    if not lock:
        logger.info("dry run: sample not written as locked file")
        return 0

    sample.to_parquet(SAMPLE_LOCKED, index=False)
    logger.info("wrote locked sample to %s", SAMPLE_LOCKED)

    identifier_columns = {
        "player_id",
        "name_canonical",
        "position_group",
        "price_quartile",
        "stratum",
    }
    population["in_text_sample"] = population["player_id"].isin(
        set(sample["player_id"])
    )
    population.to_parquet(OUT_PLAYERS, index=False)
    logger.info(
        "marked %d players in_text_sample in %s",
        int(population["in_text_sample"].sum()),
        OUT_PLAYERS,
    )

    config["text_sample"]["locked"] = True
    config["text_sample"]["locked_at"] = date.today().isoformat()
    CONFIG_PATH.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    logger.info("config marked locked at %s", config["text_sample"]["locked_at"])

    del identifier_columns  # documented intent, not used further
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(lock="--lock" in sys.argv))
