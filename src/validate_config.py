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

    numeric_cap = config.get("output", {}).get("numeric_cap")
    if not isinstance(numeric_cap, dict):
        problems.append("output.numeric_cap must be configured")
    else:
        t1 = numeric_cap.get("tier1_max_ratio")
        if not isinstance(t1, (int, float)) or isinstance(t1, bool) or not (0 < t1 <= 0.20):
            problems.append(
                f"output.numeric_cap.tier1_max_ratio ({t1!r}) must be in (0, 0.20]"
            )
        t2 = numeric_cap.get("tier2_max_ratio")
        if not isinstance(t2, (int, float)) or isinstance(t2, bool) or not (0 < t2 <= 0.35):
            problems.append(
                f"output.numeric_cap.tier2_max_ratio ({t2!r}) must be in (0, 0.35]"
            )
        max_cols = numeric_cap.get("tier2_max_numeric_cols")
        if not isinstance(max_cols, int) or isinstance(max_cols, bool) or not (1 <= max_cols <= 6):
            problems.append(
                f"output.numeric_cap.tier2_max_numeric_cols ({max_cols!r}) must be in [1, 6]"
            )
        if numeric_cap.get("treat_id_as_string") is not True:
            problems.append("output.numeric_cap.treat_id_as_string must be true")
        if numeric_cap.get("treat_bool_as_non_numeric") is not True:
            problems.append("output.numeric_cap.treat_bool_as_non_numeric must be true")

    return problems


def check_numeric_cap(
    numeric_cols: int,
    total_cols: int,
    max_ratio: float,
    max_numeric_cols: int | None = None,
) -> list[str]:
    """Validate a dataset schema against a Dual-Tier Numeric Cap."""
    issues: list[str] = []
    if total_cols <= 0:
        issues.append(f"total_cols ({total_cols}) must be positive")
        return issues
    if numeric_cols < 0 or numeric_cols > total_cols:
        issues.append(f"numeric_cols ({numeric_cols}) must be in [0, {total_cols}]")
        return issues

    ratio = numeric_cols / total_cols
    if ratio > max_ratio + 1e-9:
        issues.append(
            f"numeric column ratio {numeric_cols}/{total_cols} ({ratio:.1%}) "
            f"exceeds cap {max_ratio:.1%}"
        )
    if max_numeric_cols is not None and numeric_cols > max_numeric_cols:
        issues.append(
            f"numeric column count {numeric_cols} exceeds cap {max_numeric_cols}"
        )
    return issues


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
