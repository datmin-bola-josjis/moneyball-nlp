"""Tests for the FotMob position code mapping.

A wrong group silently corrupts every positional z-score downstream, so the
mapping is tested for unknown codes rather than assumed to be complete.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.population.positions import (
    DEEPSTATS_CODE_LABELS,
    DEEPSTATS_CODE_TO_GROUP,
    UnknownPositionCode,
    to_position_group,
    to_position_label,
)

RAW_MINUTES = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
    / "fotmob"
    / "mins_played.json"
)

VALID_GROUPS = {"GK", "DEF", "MID", "FWD"}


def test_every_mapped_code_lands_in_a_valid_group() -> None:
    assert set(DEEPSTATS_CODE_TO_GROUP.values()) <= VALID_GROUPS


def test_known_keepers_map_to_gk() -> None:
    assert to_position_group(11) == "GK"


def test_center_back_variants_all_map_to_def() -> None:
    # FotMob splits center backs across four codes; all must be DEF.
    for code in (33, 34, 35, 36, 37):
        assert to_position_group(code) == "DEF", f"code {code}"


def test_striker_codes_map_to_fwd() -> None:
    for code in (104, 105, 106, 115):
        assert to_position_group(code) == "FWD", f"code {code}"


def test_wingers_are_forwards_not_midfielders() -> None:
    # A winger sits in FWD for positional comparison; getting this wrong
    # would compare attackers against midfielders.
    for code in (82, 87, 103, 107):
        assert to_position_group(code) == "FWD", f"code {code}"


def test_labels_are_readable_not_codes() -> None:
    assert to_position_label(11) == "Keeper"
    assert to_position_label(115) == "Striker"


@pytest.mark.parametrize("code", ["11", 11])
def test_string_codes_are_accepted(code: str | int) -> None:
    """JSON gives strings in some places; both forms must work."""
    assert to_position_group(code) == "GK"


# ------------------------------------------------------------------ negative


def test_unknown_code_raises_instead_of_guessing() -> None:
    with pytest.raises(UnknownPositionCode):
        to_position_group(9999)


def test_none_raises() -> None:
    with pytest.raises(UnknownPositionCode):
        to_position_group(None)


def test_non_numeric_raises() -> None:
    with pytest.raises(UnknownPositionCode):
        to_position_group("striker")


# ------------------------------------------------------------------ boundary


def test_no_label_outside_valid_groups() -> None:
    """Guard against adding a label that was never mapped to a group."""
    from src.population.positions import LABEL_TO_GROUP

    unmapped = [label for label in DEEPSTATS_CODE_LABELS.values() if label not in LABEL_TO_GROUP]
    assert unmapped == []


@pytest.mark.skipif(not RAW_MINUTES.exists(), reason="cached FotMob data not present")
def test_mapping_covers_every_code_in_real_data() -> None:
    """Every code the live API actually emitted must be mapped."""
    payload = json.loads(RAW_MINUTES.read_text(encoding="utf-8"))
    observed = {row["position"] for row in payload["statsData"]}
    unknown = observed - set(DEEPSTATS_CODE_LABELS)

    assert unknown == set(), (
        f"FotMob emitted unmapped position codes {sorted(unknown)}; "
        "check the official label in playerData before adding them"
    )


# --------------------------------------------------- regression: code 83

def test_code_83_is_forward_not_midfield() -> None:
    """deepstats labels code 83 "Right Midfielder" but the players are wingers.

    22 of the 26 players carrying code 83 report "Right Winger" as their main
    position in playerData, and their per-90 tackle rate (1.58) matches the
    winger codes rather than the midfielder codes (2.06 to 2.38). Mapping it
    to MID compared Saka and Salah against central midfielders.
    """
    assert to_position_group(83) == "FWD"


def test_wingers_share_the_same_group_across_codes() -> None:
    """Left and right wingers must land in one group for a positional z-score."""
    assert to_position_group(87) == to_position_group(83)
    assert to_position_group(103) == to_position_group(83)


def test_wing_backs_stay_defenders() -> None:
    """A wing-back is a defender; only the winger codes moved."""
    assert to_position_group(62) == "DEF"
    assert to_position_group(68) == "DEF"
