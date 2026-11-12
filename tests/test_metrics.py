"""Tests for numeric metrics and positional z-scores.

The unit tests here encode what was verified against the live FotMob API, not
what the stat names suggest. ``total_tackle`` and ``accurate_pass`` are per 90
despite the name; ``goals`` and ``expected_goals`` are totals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.score.metrics import (
    STAT_SPECS,
    StatSpec,
    build_metrics,
    load_stat,
    rating_zscore_within_position,
    validate_metrics,
)


def write_stat(directory: Path, name: str, rows: dict[int, float | None]) -> None:
    payload = {
        "statsData": [
            {
                "id": player_id,
                "name": f"P{player_id}",
                "position": 11,
                "statValue": {"value": value},
            }
            for player_id, value in rows.items()
        ]
    }
    (directory / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def stats_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "stats"
    directory.mkdir()
    write_stat(directory, "rating", {1: 7.0, 2: 7.5, 3: 8.0})
    write_stat(directory, "expected_goals_per_90", {1: 0.2, 2: None, 3: 0.9})
    return directory


def population() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": ["fotmob_1", "fotmob_2", "fotmob_3"],
            "fotmob_id": [1, 2, 3],
            "position_group": ["MID", "MID", "MID"],
            "minutes": [2000, 1500, 2500],
        }
    )


# ------------------------------------------------------------------ loading


def test_load_stat_skips_null_values(stats_dir: Path) -> None:
    values = load_stat("expected_goals_per_90", stats_dir)

    assert values == {1: 0.2, 3: 0.9}


def test_load_stat_missing_file_returns_empty(stats_dir: Path) -> None:
    assert load_stat("does_not_exist", stats_dir) == {}


def test_build_metrics_keeps_players_without_a_stat(stats_dir: Path) -> None:
    """An inner join would drop players; coverage is genuinely partial."""
    frame = build_metrics(population(), stats_dir=stats_dir)

    assert len(frame) == 3
    assert frame["xg_per90"].isna().sum() == 1


def test_build_metrics_requires_fotmob_id(stats_dir: Path) -> None:
    with pytest.raises(ValueError):
        build_metrics(population().drop(columns=["fotmob_id"]), stats_dir=stats_dir)


def test_build_metrics_maps_by_fotmob_id_not_position(stats_dir: Path) -> None:
    shuffled = population().iloc[::-1].reset_index(drop=True)

    frame = build_metrics(shuffled, stats_dir=stats_dir)

    row = frame.loc[frame["fotmob_id"] == 1].iloc[0]
    assert row["xg_per90"] == 0.2


# ------------------------------------------------------------ z-score


def test_zscore_mean_zero_within_position() -> None:
    frame = pd.DataFrame(
        {
            "player_id": [f"p{i}" for i in range(6)],
            "position_group": ["MID"] * 6,
            "minutes": [2000] * 6,
            "avg_rating": [7.0, 7.2, 7.4, 7.6, 7.8, 8.0],
        }
    )

    z = rating_zscore_within_position(frame)

    assert z.mean() == pytest.approx(0.0, abs=1e-9)
    assert z.std(ddof=0) == pytest.approx(1.0, abs=1e-9)


def test_zscore_separate_per_position() -> None:
    """A 7.5 rating must score differently for a keeper than for a forward."""
    frame = pd.DataFrame(
        {
            "player_id": ["gk1", "gk2", "fw1", "fw2"],
            "position_group": ["GK", "GK", "FWD", "FWD"],
            "minutes": [2000] * 4,
            "avg_rating": [6.0, 7.0, 7.0, 8.0],
        }
    )

    z = rating_zscore_within_position(frame)

    # Same rating 7.0, opposite z-scores depending on the group.
    assert z.loc[1] > 0
    assert z.loc[2] < 0


def test_zscore_null_below_minutes_threshold() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "position_group": ["MID"] * 3,
            "minutes": [2000, 2000, 500],
            "avg_rating": [7.0, 8.0, 9.0],
        }
    )

    z = rating_zscore_within_position(frame)

    assert pd.isna(z.loc[2])


# ------------------------------------------------------------------ boundary


def test_zscore_group_with_one_rating_is_null() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b"],
            "position_group": ["GK", "MID"],
            "minutes": [2000, 2000],
            "avg_rating": [7.0, 6.0],
        }
    )

    z = rating_zscore_within_position(frame)

    assert z.isna().all()


def test_zscore_zero_spread_does_not_divide_by_zero() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b"],
            "position_group": ["MID", "MID"],
            "minutes": [2000, 2000],
            "avg_rating": [7.0, 7.0],
        }
    )

    z = rating_zscore_within_position(frame)

    assert z.isna().all()


def test_zscore_ignores_missing_ratings() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c"],
            "position_group": ["MID"] * 3,
            "minutes": [2000] * 3,
            "avg_rating": [7.0, None, 8.0],
        }
    )

    z = rating_zscore_within_position(frame)

    assert pd.isna(z.loc[1])
    assert not pd.isna(z.loc[0])


# --------------------------------------------------------------------- gate


def test_metrics_gate_flags_rating_out_of_range() -> None:
    frame = population().assign(avg_rating=[7.0, 7.5, 11.0])

    problems = validate_metrics(frame)

    assert any("outside 0-10" in problem for problem in problems)


def test_metrics_gate_flags_low_rating_coverage() -> None:
    frame = population().assign(avg_rating=[7.0, None, None])

    problems = validate_metrics(frame)

    assert any("coverage" in problem for problem in problems)


def test_metrics_gate_flags_duplicate_ids() -> None:
    frame = population()
    frame.loc[2, "player_id"] = "fotmob_1"

    problems = validate_metrics(frame)

    assert any("not unique" in problem for problem in problems)


def test_metrics_gate_passes_on_clean_frame() -> None:
    frame = population().assign(avg_rating=[7.0, 7.5, 8.0])

    assert validate_metrics(frame) == []


def test_specs_have_unique_columns() -> None:
    columns = [spec.column for spec in STAT_SPECS]

    assert len(columns) == len(set(columns))


def test_spec_units_are_only_known_values() -> None:
    assert {spec.unit for spec in STAT_SPECS} <= {"total", "per90"}


def test_every_spec_is_a_stat_spec() -> None:
    assert all(isinstance(spec, StatSpec) for spec in STAT_SPECS)
