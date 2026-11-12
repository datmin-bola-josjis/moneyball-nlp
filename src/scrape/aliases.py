"""Name-alias matching for per-player retrieval (AGENTS.md rule 17).

An alias shared by two players in the population, or a bare surname, is
ambiguous: matching it needs club or league context. Everything here is pure so
the ambiguous cases can be tested without network.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from src.scrape.players import Player, club_needles

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})


_POSSESSIVE = re.compile(r"(?<=[a-z0-9])'s\b")
# An apostrophe only survives between letters, so "N'Golo" is kept and the
# dangling one in "Jones' pass" is dropped.
_EDGE_APOSTROPHE = re.compile(r"(?<![a-z0-9])'|'(?![a-z0-9])")


def normalize(text: str) -> str:
    """Lowercase, de-accent, drop possessives, turn punctuation into spaces.

    The possessive goes because "Saka's finishing" has to match the alias
    "Saka". Internal apostrophes stay, so "N'Golo" and "O'Brien" survive.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_APOSTROPHES))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    without_possessive = _POSSESSIVE.sub("", stripped.lower())
    spaced = re.sub(r"[^a-z0-9']+", " ", without_possessive)
    return _EDGE_APOSTROPHE.sub("", spaced).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t]


@dataclass
class AliasIndex:
    players: dict[str, Player]
    alias_owners: dict[str, set[str]] = field(default_factory=dict)
    token_index: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, players: Iterable[Player]) -> "AliasIndex":
        index = cls(players={p.player_id: p for p in players})
        for player in index.players.values():
            for alias in player.aliases:
                norm = normalize(alias)
                if not norm:
                    continue
                index.alias_owners.setdefault(norm, set()).add(player.player_id)
                for token in set(_tokens(alias)):
                    index.token_index.setdefault(token, set()).add(player.player_id)
        return index

    def is_ambiguous(self, alias: str) -> bool:
        """True when matching this alias alone would need club/league context.

        A single token that is only *part* of a player's name ("Silva",
        "Bernardo") is ambiguous even if no other player in the population shares
        it: the sample is 70 of ~400 players, so a unique surname today proves
        nothing about the text. Time to disambiguate with context.
        """
        norm = normalize(alias)
        owners = self.alias_owners.get(norm, set())
        if len(owners) > 1:
            return True
        tokens = _tokens(alias)
        if len(tokens) == 1 and len(self.token_index.get(tokens[0], set())) > 1:
            return True
        if len(tokens) == 1:
            full_names = {normalize(self.players[pid].name) for pid in owners} or {""}
            return norm not in full_names
        return False

    def aliases_for(self, player_id: str) -> list[str]:
        """Distinct aliases, one per normalised spelling (accented form wins)."""
        seen: dict[str, str] = {}
        for alias in self.players[player_id].aliases:
            norm = normalize(alias)
            if norm:
                seen.setdefault(norm, alias)
        return list(seen.values())

    def query_terms(self, player: Player, max_terms: int = 4) -> list[str]:
        """Most specific aliases first: long, multi-token, unambiguous."""
        scored = []
        for alias in self.aliases_for(player.player_id):
            score = (
                3 * (not self.is_ambiguous(alias))
                + 2 * (len(_tokens(alias)) > 1)
                + min(len(normalize(alias)), 20) / 20
            )
            scored.append((score, alias))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [alias for _, alias in scored[:max_terms]]

    # ------------------------------------------------------------------ match
    def find_mentions(self, text: str, player_id: str) -> str | None:
        """Return the alias that names this player in `text`, most specific first.

        An ambiguous match is still returned: whether the surrounding text pins it
        down is `has_context`'s call, not this function's.
        """
        haystack = f" {normalize(text)} "
        candidates = self.query_terms(self.players[player_id], max_terms=99)
        for alias in candidates:
            if f" {normalize(alias)} " in haystack:
                return alias
        return None

    def has_context(
        self,
        text: str,
        player_id: str,
        league_clubs: Iterable[str],
        implicit_club: bool = False,
    ) -> bool:
        """Does the surrounding text pin this ambiguity to the player's own club?

        An implicit club (posting inside the player's own club subreddit) counts;
        a mention of *another* Premier League club does not, because that is
        exactly the confusable case rule 17 warns about. The league name is not
        enough either - every text here is already Premier League text.
        """
        if implicit_club:
            return True
        player = self.players[player_id]
        haystack = f" {normalize(text)} "
        needles = [normalize(n) for n in club_needles(player.club, league_clubs)]
        return any(needle and f" {needle} " in haystack for needle in needles)

    def resolves(
        self,
        alias: str | None,
        text: str,
        player_id: str,
        league_clubs: Iterable[str],
        implicit_club: bool = False,
    ) -> bool:
        """Is this mention safe to link to the player? (AGENTS.md rule 17)

        A specific alias resolves on its own. A bare surname ("Silva") survives
        only when the text itself pins it to the player's club, or the text came
        from that club's own subreddit. Every provider must go through here, so
        the disambiguation rule cannot drift between retrieval paths.
        """
        if not alias:
            return False
        if not self.is_ambiguous(alias):
            return True
        return self.has_context(text, player_id, league_clubs, implicit_club)

    def alias_debug(self) -> list[tuple[str, list[str]]]:
        """Ambiguous aliases and their owners - the Day 1 audit list."""
        rows = []
        for alias, owners in sorted(self.alias_owners.items()):
            if len(owners) > 1 or self.is_ambiguous(alias):
                rows.append((alias, sorted(owners)))
        return rows
