"""Assemble the ``players`` table from cached FotMob payloads.

Exits producing ``data/processed/players.parquet`` matching the schema in
docs/PRD.md section 8, plus the alias table the scrapers consume.

Two rules from AGENTS.md shape this module:

* the population comes from structured data, never from text
* a player below the minutes threshold never enters the population

Market value is read from the last observation inside the season window.
FotMob keeps a full history and the newest point can sit outside the season,
so taking ``values[-1]`` blindly would import a post-season valuation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.population.identity import (
    alias_key,
    ambiguous_aliases,
    generate_aliases,
    make_player_id,
)
from src.population.positions import to_position_group, to_position_label

logger = logging.getLogger(__name__)

RAW_MINUTES = Path("data/raw/fotmob/mins_played.json")
RAW_PLAYERS = Path("data/raw/fotmob/players")
RAW_TEAMS = Path("data/raw/fotmob/teams")
OUT_PLAYERS = Path("data/processed/players.parquet")

SEASON_START = date(2025, 7, 1)
SEASON_END = date(2026, 5, 31)


def normalise_club(raw: str, aliases: dict[str, str] | None = None) -> str:
    """Map a source-specific club name to the canonical name in config."""
    if aliases and raw in aliases:
        return aliases[raw]
    return raw


def load_team_names(
    teams_dir: Path = RAW_TEAMS, aliases: dict[str, str] | None = None
) -> dict[int, str]:
    """Map FotMob team id to club name for the season in question.

    The club must come from the ``teamId`` on the season stats row, not from
    ``playerData.primaryTeam``. ``primaryTeam`` is the player's *current* club,
    so using it puts Salah at Trabzonspor and inflates the league to 57 clubs.
    """
    names: dict[int, str] = {}
    for path in sorted(teams_dir.glob("team_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("corrupt team file: %s", path.name)
            continue
        details = payload.get("details") or {}
        name = details.get("name") or payload.get("name")
        team_id = path.stem.removeprefix("team_")
        if name and team_id.isdigit():
            names[int(team_id)] = normalise_club(str(name), aliases)
    return names


@dataclass
class PlayerRecord:
    """One row of the ``players`` table."""

    player_id: str
    fotmob_id: int
    name_canonical: str
    name_aliases: list[str] = field(default_factory=list)
    position: str = ""
    position_group: str = ""
    club: str = ""
    league: str = "Premier League"
    season: str = "2025/26"
    nationality: str = ""
    birth_date: str = ""
    minutes: int = 0
    market_value_eur: float | None = None
    market_value_date: str = ""
    in_text_sample: bool = False


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def market_value_in_season(
    payload: dict[str, Any],
    season_start: date = SEASON_START,
    season_end: date = SEASON_END,
) -> tuple[float | None, str]:
    """Return the last market value observed inside the season window.

    Returns ``(None, "")`` when the player has no observation in the window.
    A player without a price is kept in the population; the price filter is
    off by design, and a missing price must not silently drop someone.
    """
    values = (payload.get("marketValues") or {}).get("values") or []
    chosen: dict[str, Any] | None = None
    for entry in values:
        observed = _parse_date(entry.get("date"))
        if observed is None:
            continue
        if season_start <= observed <= season_end:
            if chosen is None or str(entry.get("date")) > str(chosen.get("date")):
                chosen = entry
    if chosen is None:
        return None, ""
    value = chosen.get("value")
    return (float(value) if isinstance(value, (int, float)) else None), str(
        chosen.get("date", "")
    )


def _information_field(payload: dict[str, Any], title: str) -> str:
    for item in payload.get("playerInformation") or []:
        if isinstance(item, dict) and item.get("title") == title:
            value = item.get("value") or {}
            if isinstance(value, dict):
                return str(value.get("fallback") or value.get("key") or "")
            return str(value)
    return ""


def build_record(
    minutes_row: dict[str, Any],
    payload: dict[str, Any],
    *,
    min_minutes: int = 900,
    team_names: dict[int, str] | None = None,
) -> PlayerRecord | None:
    """Turn a minutes row plus its payload into a record, or None to skip."""
    minutes_value = (minutes_row.get("statValue") or {}).get("value")
    if not isinstance(minutes_value, (int, float)) or minutes_value < min_minutes:
        return None

    fotmob_id = int(minutes_row["id"])
    name = payload.get("name") or minutes_row.get("name") or ""
    if not name:
        return None

    value, value_date = market_value_in_season(payload)

    # Club comes from the season row, never from playerData.primaryTeam.
    team_id = minutes_row.get("teamId")
    club = ""
    if team_names and team_id is not None:
        club = team_names.get(int(team_id), "")

    birth = payload.get("birthDate") or {}

    return PlayerRecord(
        player_id=make_player_id(fotmob_id),
        fotmob_id=fotmob_id,
        name_canonical=name,
        name_aliases=generate_aliases(name),
        position=to_position_label(minutes_row["position"]),
        position_group=to_position_group(minutes_row["position"]),
        club=club,
        nationality=_information_field(payload, "Country"),
        birth_date=str(birth.get("utcTime") or "")[:10],
        minutes=int(minutes_value),
        market_value_eur=value,
        market_value_date=value_date,
    )


def drop_colliding_aliases(
    records: list[PlayerRecord],
) -> dict[str, list[str]]:
    """Remove aliases claimed by more than one player, in place.

    A shared alias would link a sentence to the wrong person, so it is dropped
    from every claimant rather than assigned to one of them. The canonical name
    always survives. Returns the collisions that were removed, for the report.
    """
    lists = {record.player_id: list(record.name_aliases) for record in records}
    collisions = ambiguous_aliases(lists)

    if not collisions:
        return {}

    names = {record.player_id: record.name_canonical for record in records}
    removed: dict[str, list[str]] = {}
    for key, player_ids in collisions.items():
        # Keep the alias only if it is some player's full canonical name.
        keepers = [pid for pid in player_ids if alias_key(names[pid]) == key]
        removed[key] = [names[pid] for pid in player_ids if pid not in keepers]

    for record in records:
        kept: list[str] = []
        for alias in record.name_aliases:
            key = alias_key(alias)
            if key in collisions and alias_key(record.name_canonical) != key:
                continue
            kept.append(alias)
        record.name_aliases = kept

    return removed


def load_population(
    *,
    minutes_file: Path = RAW_MINUTES,
    players_dir: Path = RAW_PLAYERS,
    min_minutes: int = 900,
    club_aliases: dict[str, str] | None = None,
) -> tuple[list[PlayerRecord], list[int]]:
    """Load every eligible player. Returns (records, ids_without_payload)."""
    payload = json.loads(minutes_file.read_text(encoding="utf-8"))
    team_names = load_team_names(aliases=club_aliases)
    records: list[PlayerRecord] = []
    missing: list[int] = []

    for row in payload["statsData"]:
        value = (row.get("statValue") or {}).get("value")
        if not isinstance(value, (int, float)) or value < min_minutes:
            continue

        cache_file = players_dir / f"playerData_id={int(row['id'])}.json"
        if not cache_file.exists():
            missing.append(int(row["id"]))
            continue

        try:
            player_payload = json.loads(cache_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("corrupt payload for %s", row["id"])
            missing.append(int(row["id"]))
            continue

        record = build_record(
            row, player_payload, min_minutes=min_minutes, team_names=team_names
        )
        if record is not None:
            records.append(record)

    return records, missing


def to_dataframe(records: list[PlayerRecord]):  # noqa: ANN201
    """Convert records to a DataFrame with a stable column order."""
    import pandas as pd

    columns = [
        "player_id",
        "fotmob_id",
        "name_canonical",
        "name_aliases",
        "position",
        "position_group",
        "club",
        "league",
        "season",
        "nationality",
        "birth_date",
        "minutes",
        "market_value_eur",
        "market_value_date",
        "in_text_sample",
    ]
    rows = [{column: getattr(record, column) for column in columns} for record in records]
    return pd.DataFrame(rows, columns=columns)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    records, missing = load_population()
    if missing:
        logger.error(
            "%d players have no cached payload (run fetch_players first): %s",
            len(missing),
            missing[:10],
        )
        return 1

    collisions = drop_colliding_aliases(records)
    if collisions:
        logger.warning(
            "%d aliases dropped as ambiguous: %s",
            len(collisions),
            list(collisions)[:10],
        )

    frame = to_dataframe(records)
    OUT_PLAYERS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT_PLAYERS, index=False)

    logger.info("wrote %s rows to %s", len(frame), OUT_PLAYERS)
    logger.info("clubs: %d", frame["club"].nunique())
    logger.info(
        "market value present: %d/%d",
        int(frame["market_value_eur"].notna().sum()),
        len(frame),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
