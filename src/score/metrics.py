"""Numeric metrics for validation: ratings and per-90 performance.

FotMob's stat names are not reliable about units. Verified against the live
API for Premier League 2025/26 (league 47, season 27110):

**Totals** (round numbers, equal ``per_90 * minutes / 90``):

* ``goals`` - 243 rows, exact match with the per-90 series
* ``expected_goals`` - 295 of 314 rows match within 15 percent
* ``expected_assists`` - 292 of 336 match within 15 percent

**Per-90 despite the name** (``total_tackle`` and ``accurate_pass`` have no
``_per_90`` suffix but are already per 90):

* ``accurate_pass`` - Rodri reads 86.7. As a total over 1513 minutes that
  would be about one accurate pass per match, which is impossible for a
  defensive midfielder. As a per-90 it is ordinary.
* ``total_tackle``, ``interception``, ``rating``, ``saves``, and every
  ``_per_90`` series.

The check used to confirm this is recorded in ``SEMANTICS_VERIFIED_ON`` so a
future reader can re-run it rather than trust the name.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import pandas as pd

logger = logging.getLogger(__name__)

STATS_DIR: Final[Path] = Path("data/raw/fotmob/stats")
OUT_METRICS: Final[Path] = Path("data/processed/metrics_numeric.parquet")

SEMANTICS_VERIFIED_ON: Final[str] = "2026-11-12"

Unit = Literal["total", "per90"]


@dataclass(frozen=True)
class StatSpec:
    """One FotMob stat, with the unit that was actually verified."""

    name: str
    unit: Unit
    column: str
    note: str = ""


# Only stats whose unit was verified. Adding one without checking invites a
# silently wrong column, which is worse than a missing column.
STAT_SPECS: Final[tuple[StatSpec, ...]] = (
    StatSpec("goals", "total", "goals", "verified: equals per_90 * minutes / 90"),
    StatSpec("expected_goals", "total", "xg", "verified against expected_goals_per_90"),
    StatSpec("expected_assists", "total", "xa", "verified against expected_assists_per_90"),
    StatSpec(
        "expected_goals_per_90",
        "per90",
        "xg_per90",
        "meets PRD section 8 requirement",
    ),
    StatSpec(
        "expected_assists_per_90",
        "per90",
        "xa_per90",
        "meets PRD section 8 requirement",
    ),
    StatSpec("rating", "per90", "avg_rating", "match rating, already an average"),
    StatSpec("total_tackle", "per90", "tackles_per90", "name misleads; already per 90"),
    StatSpec("interception", "per90", "interceptions_per90", "already per 90"),
    StatSpec("accurate_pass", "per90", "accurate_pass_per90", "name misleads; already per 90"),
    StatSpec(
        "saves",
        "per90",
        "saves_per90",
        "goalkeepers only; FotMob lists 20 with >=1800 minutes, so the four "
        "keepers below that cut-off read null rather than zero",
    ),
)

# FotMob returns partial leaderboards for some stats rather than a row per
# player. ``saves`` covers 20 goalkeepers, all with at least 1800 minutes;
# the four keepers under that bound are absent, not zero. Recorded here so
# nobody reads the nulls as "made no saves".
KNOWN_COVERAGE_LIMITS: Final[dict[str, str]] = {
    "saves": "leaderboard only: 20 keepers, all >=1800 minutes",
    "goals": "counts only players who scored; a null means zero goals",
    "expected_goals": "present for 444 of 537 players; null means very low xG",
}


def load_stat(name: str, stats_dir: Path = STATS_DIR) -> dict[int, float]:
    """Return ``{fotmob_id: value}`` for one cached stat, skipping nulls."""
    import json

    path = stats_dir / f"{name}.json"
    if not path.exists():
        logger.warning("stat file missing: %s", path)
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    values: dict[int, float] = {}
    for row in payload.get("statsData") or []:
        raw = (row.get("statValue") or {}).get("value")
        if isinstance(raw, (int, float)):
            values[int(row["id"])] = float(raw)
    return values


def build_metrics(
    players: pd.DataFrame,
    *,
    stats_dir: Path = STATS_DIR,
    specs: tuple[StatSpec, ...] = STAT_SPECS,
) -> pd.DataFrame:
    """Join cached stats onto the population, one column per verified stat.

    Left join on ``fotmob_id``: a player without a given stat keeps a null in
    that column and is never dropped. Rating coverage is genuinely partial
    (291 of 340 players have one), so an inner join would quietly remove 49
    players from the validation set.
    """
    frame = players.copy()
    if "fotmob_id" not in frame.columns:
        raise ValueError("players frame must carry fotmob_id")

    for spec in specs:
        values = load_stat(spec.name, stats_dir)
        frame[spec.column] = frame["fotmob_id"].map(values)

        covered = int(frame[spec.column].notna().sum())
        logger.debug("%s: %d/%d players", spec.column, covered, len(frame))

    return frame


def rating_zscore_within_position(
    frame: pd.DataFrame,
    *,
    rating_column: str = "avg_rating",
    group_column: str = "position_group",
    minutes_column: str = "minutes",
    min_minutes: int = 900,
) -> pd.Series:
    """Z-score the rating inside each position group.

    Minutes-weighting is deliberately not used: a weighted mean is not a
    z-score, and mixing the two produces a number that is neither. Instead the
    minutes threshold is applied first and then a plain z-score is computed,
    which is what docs/PRD.md section 9 describes.

    Returns a Series aligned to ``frame.index``; null where undefined.
    """
    result = pd.Series(index=frame.index, dtype="float64")
    eligible = frame[minutes_column] >= min_minutes

    for group, subset in frame[eligible].groupby(group_column, observed=True):
        ratings = subset[rating_column].dropna()
        if len(ratings) < 2:
            logger.warning("group %s has %d ratings; z-score undefined", group, len(ratings))
            continue
        std = ratings.std(ddof=0)
        if not std:
            logger.warning("group %s has zero rating spread; z-score undefined", group)
            continue
        result.loc[ratings.index] = (ratings - ratings.mean()) / std

    return result


def validate_metrics(frame: pd.DataFrame) -> list[str]:
    """Check the metrics table before it is written. Empty list means OK."""
    problems: list[str] = []

    if frame.empty:
        return ["metrics frame is empty"]

    if "player_id" not in frame.columns:
        problems.append("missing player_id")
    elif not frame["player_id"].is_unique:
        problems.append("player_id is not unique")

    if "minutes" in frame.columns:
        under = int((frame["minutes"] < 900).sum())
        if under:
            problems.append(f"{under} players below the 900-minute threshold")

    if "avg_rating" in frame.columns:
        ratings = frame["avg_rating"].dropna()
        if ratings.empty:
            problems.append("no ratings at all")
        else:
            if ratings.min() < 0 or ratings.max() > 10:
                problems.append(
                    f"rating outside 0-10: min={ratings.min()}, max={ratings.max()}"
                )
            covered = len(ratings) / len(frame)
            if covered < 0.5:
                problems.append(f"rating coverage only {covered:.0%}")

    return problems
