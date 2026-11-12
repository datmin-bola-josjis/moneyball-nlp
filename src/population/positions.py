"""FotMob position codes mapped to the project's four position groups.

FotMob exposes two different position code systems, which is a genuine trap:

  * ``leagueseasondeepstats`` returns a numeric code per player in the
    ``position`` field (e.g. 115 for Haaland).
  * ``playerData`` returns ``positionDescription.positions[].strPos.label``
    plus its own ``position`` code (104 for Haaland), which differs.

The mapping below is keyed by the code that ``deepstats`` emits, because that
is the endpoint the population is built from. Each entry records the official
label read from ``playerData`` so the mapping is auditable rather than guessed
from player names.

Verified 2026-11-12 against Premier League 2025/26 (league 47, season 27110),
one representative player per code. All 34 codes observed in the data are
covered; ``test_position_map_covers_all_observed_codes`` enforces that.
"""

from __future__ import annotations

from typing import Final

# deepstats code -> official FotMob label (from playerData.positionDescription)
DEEPSTATS_CODE_LABELS: Final[dict[int, str]] = {
    2: "Defensive Midfielder",
    11: "Keeper",
    32: "Right Back",
    33: "Center Back",
    34: "Center Back",
    35: "Center Back",
    36: "Center Back",
    37: "Center Back",
    38: "Left Back",
    62: "Right Wing-Back",
    64: "Defensive Midfielder",
    65: "Defensive Midfielder",
    66: "Defensive Midfielder",
    68: "Left Wing-Back",
    71: "Right Midfielder",
    72: "Right Midfielder",
    73: "Central Midfielder",
    74: "Central Midfielder",
    75: "Central Midfielder",
    76: "Central Midfielder",
    77: "Central Midfielder",
    82: "Right Winger",
    83: "Right Midfielder",
    84: "Attacking Midfielder",
    85: "Attacking Midfielder",
    86: "Attacking Midfielder",
    87: "Left Winger",
    88: "Left Winger",
    103: "Right Winger",
    104: "Striker",
    105: "Striker",
    106: "Striker",
    107: "Left Winger",
    115: "Striker",
}

# Official label -> one of the four groups used for positional z-scores.
LABEL_TO_GROUP: Final[dict[str, str]] = {
    "Keeper": "GK",
    "Center Back": "DEF",
    "Right Back": "DEF",
    "Left Back": "DEF",
    "Right Wing-Back": "DEF",
    "Left Wing-Back": "DEF",
    "Defensive Midfielder": "MID",
    "Central Midfielder": "MID",
    "Attacking Midfielder": "MID",
    "Right Midfielder": "MID",
    "Left Midfielder": "MID",
    "Striker": "FWD",
    "Right Winger": "FWD",
    "Left Winger": "FWD",
}

DEEPSTATS_CODE_TO_GROUP: Final[dict[int, str]] = {
    code: LABEL_TO_GROUP[label] for code, label in DEEPSTATS_CODE_LABELS.items()
}


class UnknownPositionCode(KeyError):
    """Raised when FotMob emits a position code the project has not mapped."""


def to_position_group(code: int | str | None) -> str:
    """Map a FotMob ``deepstats`` position code to GK, DEF, MID or FWD.

    Raises ``UnknownPositionCode`` rather than guessing. A silently wrong
    group would corrupt every positional z-score downstream, and that failure
    would be invisible in the output.
    """
    if code is None:
        raise UnknownPositionCode("position code is None")
    try:
        key = int(code)
    except (TypeError, ValueError) as exc:
        raise UnknownPositionCode(f"non-numeric position code: {code!r}") from exc

    try:
        return DEEPSTATS_CODE_TO_GROUP[key]
    except KeyError as exc:
        raise UnknownPositionCode(
            f"unmapped FotMob position code {key}; add it to "
            "DEEPSTATS_CODE_LABELS after checking the official label"
        ) from exc


def to_position_label(code: int | str | None) -> str:
    """Return the official FotMob position label for a ``deepstats`` code."""
    key = int(code)  # type: ignore[arg-type]
    try:
        return DEEPSTATS_CODE_LABELS[key]
    except KeyError as exc:
        raise UnknownPositionCode(f"unmapped FotMob position code {key}") from exc
