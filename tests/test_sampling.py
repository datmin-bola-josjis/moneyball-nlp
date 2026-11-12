"""Tests for stratified sampling and the pre-lock gate.

The behaviour under test is AGENTS.md rule 15: price must stratify the text
sample even though it must never filter the population.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.population.sampling import (
    SampleConfig,
    assign_price_quartiles,
    stratified_sample,
    verify_sample,
)


def make_population(per_cell: int = 12, prices=(1e6, 5e6, 20e6, 60e6)) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group in ("GK", "DEF", "MID", "FWD"):
        for quartile, price in enumerate(prices, start=1):
            for index in range(per_cell):
                rows.append(
                    {
                        "player_id": f"fotmob_{group}{quartile}{index}",
                        "position_group": group,
                        "market_value_eur": price * (1 + index * 0.05),
                    }
                )
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ quartiles


def test_quartiles_computed_within_position() -> None:
    frame = make_population()
    labels = assign_price_quartiles(frame)

    # Each position group should span all four quartiles.
    combined = frame.assign(quartile=labels)
    for group in ("GK", "DEF", "MID", "FWD"):
        values = set(combined.loc[combined["position_group"] == group, "quartile"])
        assert values == {"Q1", "Q2", "Q3", "Q4"}


def test_cheap_defender_is_q1_even_if_expensive_overall() -> None:
    """Quartiles are per position, so a cheap defender must not land in Q4."""
    frame = pd.DataFrame(
        {
            "player_id": ["fotmob_a", "fotmob_b", "fotmob_c", "fotmob_d"],
            "position_group": ["DEF", "DEF", "DEF", "DEF"],
            "market_value_eur": [1e6, 2e6, 3e6, 4e6],
        }
    )
    labels = assign_price_quartiles(frame)

    assert labels.iloc[0] == "Q1"
    assert labels.iloc[-1] == "Q4"


def test_missing_price_labelled_na_not_dropped() -> None:
    frame = make_population(per_cell=4)
    frame.loc[0, "market_value_eur"] = None

    labels = assign_price_quartiles(frame)

    assert "NA" in set(labels)
    assert len(labels) == len(frame)


# -------------------------------------------------------------------- sampling


def test_sample_size_matches_target() -> None:
    sample = stratified_sample(make_population(), SampleConfig(target_players=70))

    assert len(sample) == 70


def test_every_cell_has_at_least_minimum() -> None:
    sample = stratified_sample(
        make_population(), SampleConfig(target_players=70, min_per_cell=4)
    )
    counts = sample.groupby(["position_group", "price_quartile"]).size()

    assert counts.min() >= 4, counts


def test_sample_includes_cheap_players_from_every_group() -> None:
    """The whole point of stratification: cheap players are not crowded out."""
    sample = stratified_sample(make_population(), SampleConfig(target_players=70))

    for group in ("GK", "DEF", "MID", "FWD"):
        cheap = sample[
            (sample["position_group"] == group)
            & (sample["price_quartile"].isin(["Q1", "Q2"]))
        ]
        assert not cheap.empty, f"{group} has no cheap players in the sample"


def test_sampling_is_deterministic_for_same_seed() -> None:
    population = make_population()
    config = SampleConfig(target_players=70, random_seed=42)

    first = stratified_sample(population, config)
    second = stratified_sample(population, config)

    assert list(first["player_id"]) == list(second["player_id"])


def test_different_seed_gives_different_sample() -> None:
    population = make_population()

    first = stratified_sample(population, SampleConfig(random_seed=1))
    second = stratified_sample(population, SampleConfig(random_seed=2))

    assert list(first["player_id"]) != list(second["player_id"])


# ------------------------------------------------------------------ boundary


def test_pool_smaller_than_quota_does_not_crash() -> None:
    frame = make_population(per_cell=1)  # 16 players, target 70

    sample = stratified_sample(frame, SampleConfig(target_players=70))

    assert len(sample) <= 16
    assert len(sample) == sample["player_id"].nunique()


def test_single_position_group_still_works() -> None:
    frame = pd.DataFrame(
        {
            "player_id": [f"fotmob_{i}" for i in range(20)],
            "position_group": ["GK"] * 20,
            "market_value_eur": [float(i) * 1e6 for i in range(20)],
        }
    )

    sample = stratified_sample(frame, SampleConfig(target_players=10))

    assert 0 < len(sample) <= 20


def test_empty_population_returns_empty_sample() -> None:
    frame = pd.DataFrame(
        columns=["player_id", "position_group", "market_value_eur"]
    )

    sample = stratified_sample(frame)

    assert sample.empty


def test_all_prices_identical_does_not_crash() -> None:
    """qcut fails when every value is the same; the fallback must hold."""
    frame = pd.DataFrame(
        {
            "player_id": [f"fotmob_{i}" for i in range(10)],
            "position_group": ["MID"] * 10,
            "market_value_eur": [5e6] * 10,
        }
    )

    sample = stratified_sample(frame, SampleConfig(target_players=5))

    assert len(sample) == 5


# --------------------------------------------------------------------- gate


def test_valid_sample_passes_gate() -> None:
    population = make_population()
    sample = stratified_sample(population, SampleConfig(target_players=70))

    problems = verify_sample(sample, population, SampleConfig(target_players=70))

    assert problems == []


def test_duplicate_player_flagged() -> None:
    population = make_population()
    sample = stratified_sample(population, SampleConfig(target_players=70))
    duplicated = pd.concat([sample, sample.iloc[[0]]], ignore_index=True)

    problems = verify_sample(duplicated, population, SampleConfig(target_players=70))

    assert any("duplicated" in problem for problem in problems)


def test_missing_position_group_flagged() -> None:
    population = make_population()
    sample = stratified_sample(population, SampleConfig(target_players=70))
    only_forwards = sample[sample["position_group"] == "FWD"]

    problems = verify_sample(only_forwards, population, SampleConfig(target_players=70))

    assert any("position groups missing" in problem for problem in problems)


def test_sample_without_cheap_players_is_rejected() -> None:
    population = make_population()
    sample = stratified_sample(population, SampleConfig(target_players=70))
    expensive_only = sample[sample["price_quartile"].isin(["Q3", "Q4"])]

    problems = verify_sample(expensive_only, population, SampleConfig(target_players=70))

    assert any("cheaper half" in problem for problem in problems)


def test_empty_sample_rejected() -> None:
    population = make_population()

    problems = verify_sample(pd.DataFrame(), population, SampleConfig())

    assert problems == ["sample is empty"]
