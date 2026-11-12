"""Population reader for Stage B.

The player list is owned by person A: ``data/processed/players.parquet`` (or a
CSV twin while pyarrow is missing). Stage B must never invent players - the
population comes from structured roster data (AGENTS.md rule 1), so a missing
file is a hard error naming the deliverable, not a silent fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.config import ROOT

DEFAULT_PLAYERS = ROOT / "data" / "processed" / "players.parquet"
_NOSEP = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    aliases: tuple[str, ...]
    club: str | None

    def __post_init__(self) -> None:
        if not self.player_id or not self.name:
            raise ValueError("player_id and name are required to build a query")


def club_key(name: str) -> str:
    """Config keys club subreddits without spaces (`ManchesterUnited`); normalise both."""
    return _NOSEP.sub("", (name or "").lower())


# Club-name words that are also ordinary English, so they cannot anchor a mention
# on their own ("we ran the city", "he looked lost in the forest"). Every club
# using one of these has a distinctive first word ("manchester", "nottingham"),
# so nothing is lost by denying them.
_GENERIC_CLUB_TOKENS = frozenset(
    {"city", "united", "town", "club", "fc", "wanderers", "albion", "athletic", "palace", "forest", "villa"}
)


def club_needles(club: str | None, league_clubs: Iterable[str] = ()) -> tuple[str, ...]:
    """Strings that give club context for disambiguation (AGENTS.md rule 17).

    Only the full club string, its squashed form, and single words that no other
    league club shares *and* that are not ordinary English. "Newcastle" resolves;
    "City" and "United" do not. Nicknames are not guessed here - inventing one is
    how a wrong club gets attached to a sentence.
    """
    if not club:
        return ()
    needles = {club_key(club), (club or "").strip().lower()}
    if league_clubs:
        for token in re.split(r"[^a-z]+", club.lower()):
            if len(token) <= 3 or token in _GENERIC_CLUB_TOKENS:
                continue
            if sum(1 for other in league_clubs if token in re.split(r"[^a-z]+", other.lower())) == 1:
                needles.add(token)
    return tuple(sorted(n for n in needles if n))


def _alias_list(value) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def load_players(path: Path | str = DEFAULT_PLAYERS) -> list[Player]:
    path = Path(path)
    if not path.exists():
        raise SystemExit(
            f"population file not found: {path}\n"
            "Stage B reads the player list from A (data/processed/players.parquet). "
            "Do not build a player list out of scraped text (AGENTS.md rule 1)."
        )
    if path.suffix == ".parquet":
        try:
            frame = pd.read_parquet(path)
        except ImportError as exc:  # pyarrow absent
            raise SystemExit(
                f"cannot read {path}: {exc}. Install the deps with `make setup`."
            ) from exc
    else:
        frame = pd.read_csv(path)

    required = {"player_id", "name_canonical"}
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"{path} is missing required columns: {sorted(missing)}")

    players: list[Player] = []
    for row in frame.itertuples(index=False):
        club = getattr(row, "club", None)
        aliases = _alias_list(getattr(row, "name_aliases", None))
        name = str(row.name_canonical).strip()
        players.append(
            Player(
                player_id=str(row.player_id),
                name=name,
                aliases=tuple(dict.fromkeys([name, *aliases])),
                club=None if pd.isna(club) else str(club),
            )
        )
    if len({p.player_id for p in players}) != len(players):
        raise SystemExit(f"{path} has duplicate player_id values - join key must be unique")
    return players


def market_values(path: Path | str = DEFAULT_PLAYERS) -> dict[str, float]:
    """Market value per `player_id`, when the population file carries the column.

    Only used to spread the pilot across the price range; it never filters the
    population (AGENTS.md rule 15).
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        frame = pd.read_csv(path) if path.suffix != ".parquet" else pd.read_parquet(path)
    except (ImportError, OSError, ValueError):
        return {}
    column = next((c for c in ("market_value_eur", "market_value") if c in frame.columns), None)
    if not column or "player_id" not in frame.columns:
        return {}
    return {
        str(pid): float(val)
        for pid, val in zip(frame["player_id"], frame[column])
        if pd.notna(val)
    }


def pilot_subset(players: list[Player], n: int, values: dict[str, float] | None = None) -> list[Player]:
    """Pick `n` players spread across the market-value range, deterministically.

    No RNG: sort by value and take every k-th row, so the pilot covers cheap and
    expensive players without a seed to record (AGENTS.md rule 14 hygiene).
    `values` is market value per `player_id` when the population file has it.
    """
    if n >= len(players):
        return list(players)
    if values:
        ordered = sorted(players, key=lambda p: (values.get(p.player_id, 0.0), p.player_id))
    else:
        ordered = sorted(players, key=lambda p: p.player_id)
    step = len(ordered) / n
    picked = [ordered[int(i * step)] for i in range(n)]
    return list(dict.fromkeys(picked))
