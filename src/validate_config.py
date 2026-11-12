"""Validate config/config.yaml shape and the invariants that must never drift.

Run directly (`python3 -m src.validate_config`) or via `make config`.
Kept as a real module rather than a shell one-liner so the checks are
readable, testable, and independent of the shell make happens to use.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"

REQUIRED_SECTIONS = (
    "project",
    "league",
    "population",
    "text_sample",
    "data_source",
    "validation",
    "text_sources",
    "retrieval",
    "nlp",
    "scoring",
    "thresholds",
    "output",
)


class ConfigError(AssertionError):
    """Raised when the config violates an invariant."""


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def validate(config: dict) -> list[str]:
    """Return a list of human-readable problems. Empty list means valid."""
    problems: list[str] = []

    missing = [key for key in REQUIRED_SECTIONS if key not in config]
    if missing:
        problems.append(f"missing sections: {missing}")

    clubs = config.get("league", {}).get("clubs", [])
    if len(clubs) != 20:
        problems.append(f"league.clubs: expected 20, got {len(clubs)}")

    # The price filter must stay off: population is never filtered by price.
    # Stratification of the *text sample* by price quartile is a different
    # thing and stays allowed (see AGENTS.md rule 15).
    population = config.get("population", {})
    if population.get("price_filter_enabled") is not False:
        problems.append(
            "population.price_filter_enabled must be false "
            "(text decides the population, not price)"
        )

    aspects = config.get("nlp", {}).get("aspects", {})
    if len(aspects) != 8:
        problems.append(f"nlp.aspects: expected 8, got {len(aspects)}")

    seed = config.get("text_sample", {}).get("random_seed")
    if seed is None:
        problems.append("text_sample.random_seed must be set for reproducible sampling")

    provider = config.get("data_source", {}).get("provider")
    rating_source = config.get("validation", {}).get("rating_source")
    if provider != rating_source:
        problems.append(
            f"data_source.provider ({provider!r}) should match "
            f"validation.rating_source ({rating_source!r}); mixing sources "
            "makes positional z-scores incomparable"
        )

    return problems


def main() -> int:
    config = load_config()
    problems = validate(config)
    if problems:
        print("config INVALID:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(
        f"config ok: {len(config)} sections, "
        f"{len(config['league']['clubs'])} clubs, "
        f"source={config['data_source']['provider']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
