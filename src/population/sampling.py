"""Stratified sampling for the text-review path.

This is where AGENTS.md rule 15 bites. Two things that look similar are not:

* market value must **not** filter the population
* market value **must** stratify the text sample

Without stratification the sample fills up with popular, expensive players,
because those are the ones with the most discussion. That is exactly the bias
the design exists to avoid, and it would quietly make the research question
unanswerable.

Sampling is deterministic: the same seed and the same input produce the same
sample, so the locked file is reproducible and auditable.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

POSITION_GROUPS = ("GK", "DEF", "MID", "FWD")
QUARTILE_LABELS = ("Q1", "Q2", "Q3", "Q4")


@dataclass(frozen=True)
class SampleConfig:
    """Parameters that define one sampling run.

    Values mirror ``config/config.yaml`` under ``text_sample``. Defaults are
    fallbacks so the module is usable in a test without loading YAML.
    """

    target_players: int = 70
    per_position_group: int = 17
    min_per_cell: int = 4
    random_seed: int = 20252026


def assign_price_quartiles(frame: pd.DataFrame) -> pd.Series:
    """Quartile label per player, computed *within position group*.

    Quartiles are computed inside each position so a cheap defender is
    compared with other defenders, not with strikers who cost more. Players
    without a price get the label ``NA`` and are handled separately rather
    than dropped.
    """
    if frame.empty:
        return pd.Series([], dtype="object", index=frame.index)

    labelled = frame.copy()
    labels = pd.Series("NA", index=labelled.index, dtype="object")

    for group in POSITION_GROUPS:
        mask = labelled["position_group"] == group
        prices = labelled.loc[mask, "market_value_eur"]
        priced = prices.dropna()
        if priced.empty:
            continue

        # rank(method="first") keeps ties from collapsing a quartile away.
        try:
            buckets = pd.qcut(
                priced.rank(method="first"), 4, labels=list(QUARTILE_LABELS)
            )
        except ValueError:
            # Fewer than four distinct prices in this group.
            buckets = pd.Series("Q1", index=priced.index, dtype="object")
        labels.loc[buckets.index] = buckets.astype(str)

    return labels


def _allocate_even(total: int, caps: Mapping[str, int], minimum: int) -> dict[str, int]:
    """Spread ``total`` as evenly as possible, capped by each key's pool size.

    Used for the position groups. docs/PRD.md section 7.A.5 asks for roughly
    15 to 20 players per position group, not a share proportional to pool
    size: goalkeepers are scarce (24 qualify) and a proportional split would
    give them six players, which is too thin to compute anything positional.
    """
    keys = list(caps)
    allocation = {key: 0 for key in keys}
    remaining = total

    # Round-robin until the budget is gone or every pool is exhausted.
    while remaining > 0:
        progressed = False
        for key in keys:
            if remaining <= 0:
                break
            room = caps[key] - allocation[key]
            if room <= 0:
                continue
            allocation[key] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            break

    # Honour the minimum where the pool allows it, at the cost of the largest.
    for key in keys:
        if allocation[key] < minimum and caps[key] >= minimum:
            shortfall = minimum - allocation[key]
            donor = max(keys, key=lambda k: allocation[k])
            if donor != key and allocation[donor] - shortfall >= 1:
                allocation[donor] -= shortfall
                allocation[key] += shortfall

    return allocation


def _allocate(total: int, weights: Mapping[str, int], minimum: int) -> dict[str, int]:
    """Distribute ``total`` across keys in proportion to pool size.

    Used *within* a position group across price quartiles, where proportional
    allocation is what we want: a cell with more players can supply more.
    """
    caps = {key: min(weights[key], max(minimum, 1)) for key in weights}
    allocation = {key: min(caps[key], total) for key in weights}

    remaining = total - sum(allocation.values())
    if remaining <= 0:
        return allocation

    capacity = {key: weights[key] - allocation[key] for key in weights}
    total_capacity = sum(capacity.values())
    if total_capacity <= 0:
        return allocation

    shares = {
        key: remaining * capacity[key] / total_capacity
        for key in weights
        if capacity[key] > 0
    }
    floor_shares = {key: int(value) for key, value in shares.items()}
    for key, value in floor_shares.items():
        allocation[key] += value

    leftover = total - sum(allocation.values())
    if leftover > 0:
        remainders = sorted(
            ((key, shares[key] - floor_shares[key]) for key in shares),
            key=lambda item: item[1],
            reverse=True,
        )
        for key, _ in remainders[:leftover]:
            if allocation[key] < weights[key]:
                allocation[key] += 1

    return allocation


def stratified_sample(
    frame: pd.DataFrame,
    config: SampleConfig | None = None,
) -> pd.DataFrame:
    """Select the text sample, balanced across position group and price quartile.

    Parameters
    ----------
    frame:
        Population with ``player_id``, ``position_group`` and
        ``market_value_eur``.
    config:
        Sampling parameters. Defaults match config/config.yaml.

    Returns
    -------
    pd.DataFrame
        The selected rows, with ``price_quartile`` and ``stratum`` columns
        added.
    """
    cfg = config or SampleConfig()
    if frame.empty:
        return frame.assign(price_quartile=[], stratum=[])

    working = frame.copy()
    working["price_quartile"] = assign_price_quartiles(working)
    working["stratum"] = working["position_group"] + "_" + working["price_quartile"]

    cells: dict[str, list[int]] = defaultdict(list)
    for index, stratum in working["stratum"].items():
        cells[stratum].append(index)

    # Even split across position groups, proportional only within a group.
    group_pools: dict[str, int] = {}
    for group in POSITION_GROUPS:
        group_pools[group] = int((working["position_group"] == group).sum())

    group_quota = _allocate_even(
        cfg.target_players, group_pools, minimum=cfg.per_position_group
    )
    logger.debug("group quotas: %s", group_quota)

    chosen: list[int] = []
    for group in POSITION_GROUPS:
        quota = group_quota.get(group, 0)
        if quota <= 0:
            continue

        group_index = working.index[working["position_group"] == group]
        group_cells = working.loc[group_index, "stratum"].value_counts().to_dict()
        if not group_cells:
            continue

        cell_quota = _allocate(quota, group_cells, minimum=min(cfg.min_per_cell, 1))

        for stratum, take in cell_quota.items():
            if take <= 0:
                continue
            pool = sorted(cells.get(stratum, []))
            if not pool:
                continue
            rng = _rng(cfg.random_seed, stratum)
            picked = rng.sample(pool, min(take, len(pool)))
            chosen.extend(picked)

    chosen = sorted(set(chosen))
    result = working.loc[chosen].copy()
    result = result.sort_values(["position_group", "price_quartile", "player_id"])
    return result.reset_index(drop=True)


def _rng(seed: int, stratum: str):  # noqa: ANN201
    """Per-stratum RNG so adding a stratum does not reshuffle the others."""
    import random

    mixed = hash((seed, stratum)) & 0xFFFFFFFF
    return random.Random(mixed)


def cell_census(frame: pd.DataFrame) -> pd.DataFrame:
    """Report pool size and selected count per stratum, for the lock gate."""
    if frame.empty:
        return pd.DataFrame(
            columns=["stratum", "selected", "population"], dtype="object"
        )
    population = (
        frame.groupby("stratum", observed=True).size().rename("population").reset_index()
    )
    selected = (
        frame.groupby("stratum", observed=True)["selected"]
        .sum()
        .rename("selected")
        .reset_index()
    )
    return population.merge(selected, on="stratum", how="left").fillna({"selected": 0})


def verify_population(
    population: pd.DataFrame, expected_clubs: Sequence[str] | None = None
) -> list[str]:
    """Check the population itself before anything is sampled from it.

    The club check exists because of a real bug: taking the club from
    ``playerData.primaryTeam`` returned each player's *current* club, which
    produced 57 clubs (Celtic, Al Hilal, Trabzonspor) and put players at the
    wrong team. Club must come from the season row's ``teamId``.
    """
    problems: list[str] = []

    if population.empty:
        return ["population is empty"]

    duplicated = int(population["player_id"].duplicated().sum())
    if duplicated:
        problems.append(f"{duplicated} duplicated player_id in population")

    blank_club = int((population["club"].fillna("") == "").sum())
    if blank_club:
        problems.append(f"{blank_club} players have no club")

    blank_position = int((population["position_group"].fillna("") == "").sum())
    if blank_position:
        problems.append(f"{blank_position} players have no position group")

    clubs = int(population["club"].nunique())
    if clubs != 20:
        problems.append(f"expected 20 clubs, found {clubs}")

    if expected_clubs is not None:
        expected = set(expected_clubs)
        found = set(population["club"].dropna())
        missing = expected - found
        unexpected = found - expected
        if missing:
            problems.append(f"clubs in config but absent from data: {sorted(missing)}")
        if unexpected:
            problems.append(f"clubs in data but not in config: {sorted(unexpected)}")

    return problems


def verify_sample(
    sample: pd.DataFrame,
    population: pd.DataFrame,
    config: SampleConfig | None = None,
) -> list[str]:
    """Check the sample before it is locked. Returns a list of problems.

    An empty list means the sample may be locked. Every check here guards a
    claim the report will make, so a failure must block locking rather than
    produce a warning that gets ignored.
    """
    cfg = config or SampleConfig()
    problems: list[str] = []

    if sample.empty:
        return ["sample is empty"]

    duplicated = sample["player_id"].duplicated().sum()
    if duplicated:
        problems.append(f"{duplicated} duplicated player_id in sample")

    if sample["player_id"].nunique() != len(sample):
        problems.append("player_id is not unique in sample")

    missing_groups = set(POSITION_GROUPS) - set(sample["position_group"])
    if missing_groups:
        problems.append(f"position groups missing from sample: {sorted(missing_groups)}")

    # Every position group must include cheap players, otherwise the sample is
    # just the famous names and the research question has no basis.
    for group in POSITION_GROUPS:
        subset = sample[sample["position_group"] == group]
        if subset.empty:
            continue
        cheap = subset[subset["price_quartile"].isin(["Q1", "Q2"])]
        if cheap.empty:
            problems.append(f"{group}: no players from the cheaper half (Q1/Q2)")

    priced = sample["market_value_eur"].notna().sum()
    if priced == 0:
        problems.append("no player in the sample has a market value")

    # A sample far below target means the population was thinner than assumed.
    if len(sample) < cfg.target_players * 0.8:
        problems.append(
            f"sample has {len(sample)} players, under 80% of target {cfg.target_players}"
        )

    unknown = set(sample["price_quartile"]) - set(QUARTILE_LABELS) - {"NA"}
    if unknown:
        problems.append(f"unexpected price quartile labels: {sorted(unknown)}")

    return problems
