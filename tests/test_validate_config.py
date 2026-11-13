"""Tests for config validation.

The invariants here are the ones that silently corrupt the project if they
drift: a price-filtered population, a missing sampling seed, or price and
rating coming from different providers.
"""

from __future__ import annotations

import copy

import pytest

from src.validate_config import check_numeric_cap, load_config, validate


@pytest.fixture()
def base_config() -> dict:
    return load_config()


def test_real_config_is_valid(base_config: dict) -> None:
    assert validate(base_config) == []


def test_valid_config_reports_provider(base_config: dict) -> None:
    assert base_config["data_source"]["provider"] == "fotmob"


# ------------------------------------------------------------------ negative


def test_missing_section_is_reported(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    del config["data_source"]

    problems = validate(config)

    assert any("missing sections" in p and "data_source" in p for p in problems)


def test_price_filter_enabled_is_rejected(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    config["population"]["price_filter_enabled"] = True

    problems = validate(config)

    assert any("price_filter_enabled" in p for p in problems)


def test_price_filter_missing_is_rejected(base_config: dict) -> None:
    """Absent is not the same as false: an unset flag must still fail."""
    config = copy.deepcopy(base_config)
    del config["population"]["price_filter_enabled"]

    problems = validate(config)

    assert any("price_filter_enabled" in p for p in problems)


def test_missing_sampling_seed_is_rejected(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    del config["text_sample"]["random_seed"]

    problems = validate(config)

    assert any("random_seed" in p for p in problems)


def test_provider_mismatch_is_rejected(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    config["validation"]["rating_source"] = "fbref"

    problems = validate(config)

    assert any("should match" in p for p in problems)


# ------------------------------------------------------------------ boundary


@pytest.mark.parametrize("club_count", [19, 21])
def test_wrong_club_count_is_rejected(base_config: dict, club_count: int) -> None:
    config = copy.deepcopy(base_config)
    clubs = list(config["league"]["clubs"])
    while len(clubs) < club_count:
        clubs.append(f"Placeholder {len(clubs)}")
    config["league"]["clubs"] = clubs[:club_count]

    problems = validate(config)

    assert any("clubs" in p for p in problems)


def test_exactly_twenty_clubs_passes(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    assert len(config["league"]["clubs"]) == 20

    assert validate(config) == []


def test_seed_zero_is_accepted(base_config: dict) -> None:
    """0 is a legitimate seed; only a missing value should fail."""
    config = copy.deepcopy(base_config)
    config["text_sample"]["random_seed"] = 0

    assert validate(config) == []


# ---------------------------------------------------------- numeric cap (M5)


def test_numeric_cap_missing_is_rejected(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    del config["output"]["numeric_cap"]

    problems = validate(config)

    assert any("numeric_cap" in p for p in problems)


def test_numeric_cap_ratio_above_limit_is_rejected(base_config: dict) -> None:
    config = copy.deepcopy(base_config)
    config["output"]["numeric_cap"]["tier2_max_ratio"] = 0.40

    problems = validate(config)

    assert any("tier2_max_ratio" in p for p in problems)


def test_player_summary_numeric_cap_boundary() -> None:
    # 6/17 = 35.3% exceeds <= 35%, while 6/19 = 31.6% passes.
    assert check_numeric_cap(6, 17, max_ratio=0.35, max_numeric_cols=6) != []
    assert check_numeric_cap(6, 19, max_ratio=0.35, max_numeric_cols=6) == []
    # 7 numeric columns fails max_numeric_cols=6 even when ratio <= 35%.
    assert check_numeric_cap(7, 25, max_ratio=0.35, max_numeric_cols=6) != []


def test_tier1_numeric_cap_boundary() -> None:
    # 2/7 = 28.6% fails <= 20%, while 2/11 = 18.2% and 1/17 = 5.9% pass.
    assert check_numeric_cap(2, 7, max_ratio=0.20) != []
    assert check_numeric_cap(2, 11, max_ratio=0.20) == []
    assert check_numeric_cap(1, 17, max_ratio=0.20) == []
