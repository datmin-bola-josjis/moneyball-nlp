"""Tests for population assembly.

The club test here is not hypothetical. Reading the club from
``playerData.primaryTeam`` (the player's current club) produced 57 clubs
including Celtic, Al Hilal and Trabzonspor, and placed Salah at Trabzonspor.
The club must come from the season row's ``teamId``.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.population.build import (
    PlayerRecord,
    drop_colliding_aliases,
    load_team_names,
    market_value_in_season,
    normalise_club,
)


def minutes_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 737066,
        "teamId": 8456,
        "name": "Erling Haaland",
        "position": 115,
        "statValue": {"value": 3000},
    }
    row.update(overrides)
    return row


def payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "Erling Haaland",
        "birthDate": {"utcTime": "2000-07-21T00:00:00.000Z"},
        "primaryTeam": {"teamName": "Trabzonspor", "teamId": 9999},
        "playerInformation": [
            {"title": "Country", "value": {"fallback": "Norway"}}
        ],
        "marketValues": {
            "values": [
                {"date": "2024-10-01T00:00:00+00:00", "value": 100},
                {"date": "2025-10-01T00:00:00+00:00", "value": 200},
                {"date": "2026-09-01T00:00:00+00:00", "value": 300},
            ]
        },
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------ market value


def test_market_value_taken_from_inside_season() -> None:
    value, observed = market_value_in_season(payload())

    assert value == 200.0
    assert observed.startswith("2025-10-01")


def test_post_season_value_is_not_used() -> None:
    """The newest FotMob point can sit after the season; it must be ignored."""
    value, _ = market_value_in_season(payload())

    assert value != 300.0


def test_no_value_in_window_returns_none() -> None:
    empty = payload(marketValues={"values": [{"date": "2024-01-01T00:00:00+00:00", "value": 5}]})

    value, observed = market_value_in_season(empty)

    assert value is None
    assert observed == ""


def test_missing_market_block_returns_none() -> None:
    value, _ = market_value_in_season(payload(marketValues={}))

    assert value is None


def test_season_window_boundaries_are_inclusive() -> None:
    at_start = payload(
        marketValues={"values": [{"date": "2025-07-01T00:00:00+00:00", "value": 42}]}
    )
    at_end = payload(
        marketValues={"values": [{"date": "2026-05-31T00:00:00+00:00", "value": 43}]}
    )

    assert market_value_in_season(at_start)[0] == 42.0
    assert market_value_in_season(at_end)[0] == 43.0


def test_just_outside_window_returns_none() -> None:
    before = payload(
        marketValues={"values": [{"date": "2025-06-30T00:00:00+00:00", "value": 1}]}
    )
    after = payload(
        marketValues={"values": [{"date": "2026-06-01T00:00:00+00:00", "value": 1}]}
    )

    assert market_value_in_season(before)[0] is None
    assert market_value_in_season(after)[0] is None


# -------------------------------------------------------------- club names


def test_normalise_club_maps_long_names() -> None:
    aliases = {"AFC Bournemouth": "Bournemouth", "Brighton & Hove Albion": "Brighton"}

    assert normalise_club("AFC Bournemouth", aliases) == "Bournemouth"
    assert normalise_club("Brighton & Hove Albion", aliases) == "Brighton"


def test_normalise_club_passes_through_unknown() -> None:
    assert normalise_club("Arsenal", {"X": "Y"}) == "Arsenal"


def test_normalise_club_without_aliases() -> None:
    assert normalise_club("Arsenal") == "Arsenal"


def test_load_team_names_reads_details_name(tmp_path) -> None:  # noqa: ANN001
    teams = tmp_path
    (teams / "team_8456.json").write_text(
        json.dumps({"details": {"name": "Manchester City"}}), encoding="utf-8"
    )
    (teams / "team_8191.json").write_text(
        json.dumps({"details": {"name": "Burnley"}}), encoding="utf-8"
    )

    names = load_team_names(teams)

    assert names == {8456: "Manchester City", 8191: "Burnley"}


def test_load_team_names_applies_aliases(tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "team_8678.json").write_text(
        json.dumps({"details": {"name": "AFC Bournemouth"}}), encoding="utf-8"
    )

    names = load_team_names(tmp_path, aliases={"AFC Bournemouth": "Bournemouth"})

    assert names[8678] == "Bournemouth"


def test_load_team_names_skips_corrupt_file(tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "team_1.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "team_2.json").write_text(
        json.dumps({"details": {"name": "Arsenal"}}), encoding="utf-8"
    )

    names = load_team_names(tmp_path)

    assert names == {2: "Arsenal"}


# ------------------------------------------------------------ alias pruning


def record(player_id: str, name: str, aliases: list[str]) -> PlayerRecord:
    return PlayerRecord(
        player_id=player_id, fotmob_id=1, name_canonical=name, name_aliases=aliases
    )


def test_colliding_alias_removed_from_both() -> None:
    records = [
        record("fotmob_1", "Bruno Fernandes", ["Bruno Fernandes", "Bruno F."]),
        record("fotmob_2", "Bruno Guimaraes", ["Bruno Guimaraes", "Bruno F."]),
    ]

    removed = drop_colliding_aliases(records)

    assert "bruno f" in removed
    assert "Bruno F." not in records[0].name_aliases
    assert "Bruno F." not in records[1].name_aliases


def test_canonical_name_survives_collision() -> None:
    records = [
        record("fotmob_1", "Pedro", ["Pedro"]),
        record("fotmob_2", "Joao Pedro", ["Joao Pedro", "Pedro"]),
    ]

    drop_colliding_aliases(records)

    # The player whose full name is "Pedro" keeps it.
    assert records[0].name_aliases == ["Pedro"]


def test_no_collision_leaves_aliases_untouched() -> None:
    records = [
        record("fotmob_1", "Mohamed Salah", ["Mohamed Salah", "Salah"]),
        record("fotmob_2", "Harry Kane", ["Harry Kane", "Kane"]),
    ]

    removed = drop_colliding_aliases(records)

    assert removed == {}
    assert "Salah" in records[0].name_aliases
