"""Player identity: stable ids and the name aliases the scrapers depend on.

Two things live here and both matter more than they look.

**player_id.** Format ``fotmob_<id>``. It is the only join key across every
table, so nothing downstream may join on a name.

**aliases.** If "Bruno G." is not an alias of Bruno Guimarães, the Reddit
scraper silently returns nothing for him. No exception, no warning, exit code
zero: the text is simply missing, and that only surfaces late in the analysis.
So alias generation is treated as a correctness surface, not a convenience.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# Particles that belong to a surname but are often dropped in casual writing.
# "van Dijk" is written both "Virgil van Dijk" and "Van Dijk".
NAME_PARTICLES: Final[frozenset[str]] = frozenset(
    {"van", "von", "de", "der", "den", "da", "dos", "di", "del", "la", "le", "ten", "ter"}
)

# Tokens too generic to identify one player on their own. "Silva" or "Junior"
# alone must never be treated as a match; AGENTS.md rule 17.
GENERIC_SURNAMES: Final[frozenset[str]] = frozenset(
    {
        "silva",
        "santos",
        "junior",
        "jones",
        "gomes",
        "silva",
        "costa",
        "pereira",
        "fernandez",
        "fernandes",
        "lopez",
        "garcia",
        "martinez",
        "rodriguez",
        "gonzalez",
        "williams",
        "brown",
        "davies",
        "johnson",
        "smith",
        "taylor",
        "wilson",
        "campbell",
        "murphy",
        "graham",
        "young",
        "adam",
        "adam",
        "silva",
    }
)

MIN_ALIAS_LENGTH: Final[int] = 3

# Characters that Unicode NFKD does NOT decompose but that authors routinely
# type as plain ASCII. Without this table "Ødegaard" never matches "Odegaard",
# which is a live Premier League name, not a hypothetical.
TRANSLITERATIONS: Final[dict[str, str]] = {
    "ø": "o",
    "Ø": "O",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ł": "l",
    "Ł": "L",
    "đ": "d",
    "Đ": "D",
    "ð": "d",
    "Ð": "D",
    "þ": "th",
    "Þ": "Th",
    "ß": "ss",
    "ı": "i",
    "İ": "I",
}


def make_player_id(fotmob_id: int | str) -> str:
    """Build the canonical internal id, e.g. ``fotmob_737066``."""
    try:
        numeric = int(fotmob_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"fotmob_id must be numeric, got {fotmob_id!r}") from exc
    if numeric <= 0:
        raise ValueError(f"fotmob_id must be positive, got {numeric}")
    return f"fotmob_{numeric}"


def player_id_to_fotmob(player_id: str) -> int:
    """Recover the numeric FotMob id from an internal id."""
    if not player_id.startswith("fotmob_"):
        raise ValueError(f"not a fotmob player_id: {player_id!r}")
    return int(player_id.removeprefix("fotmob_"))


def strip_accents(text: str) -> str:
    """Fold accents so "Šeško" also matches "Sesko".

    NFKD handles most Latin diacritics but leaves ø, æ, ł, đ and ß intact,
    so those are transliterated first. "Ødegaard" is a real Premier League
    name and would otherwise never match "Odegaard".
    """
    transliterated = "".join(TRANSLITERATIONS.get(char, char) for char in text)
    decomposed = unicodedata.normalize("NFKD", transliterated)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_name(full_name: str) -> tuple[str, str]:
    """Split into (given, family), keeping a particle with the surname.

    "Virgil van Dijk" splits as ("Virgil", "van Dijk"), not ("Virgil van",
    "Dijk"), because the surname is what people write and search for.
    """
    parts = [p for p in normalise_whitespace(full_name).split(" ") if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""

    # Walk back from the end while the preceding token is a particle.
    index = len(parts) - 1
    while index - 1 > 0 and parts[index - 1].casefold() in NAME_PARTICLES:
        index -= 1

    return " ".join(parts[:index]), " ".join(parts[index:])


def generate_aliases(full_name: str) -> list[str]:
    """Return matchable aliases for a player name.

    The list always contains the canonical name first, then accent-folded,
    short, and surname forms. Generic surnames are deliberately excluded so a
    single "Silva" never links one sentence to the wrong player.

    Parameters
    ----------
    full_name:
        Display name as FotMob reports it, e.g. "Bruno Guimarães".

    Returns
    -------
    list[str]
        De-duplicated aliases, canonical form first.
    """
    canonical = normalise_whitespace(full_name)
    if not canonical:
        return []

    candidates: list[str] = [canonical]

    folded = strip_accents(canonical)
    candidates.append(folded)

    given, family = split_name(folded)
    if family:
        candidates.append(family)

        # Initial + surname: "B. Guimaraes" style matching.
        if given:
            first_initial = given.split(" ")[0][0]
            candidates.append(f"{first_initial}. {family}")

    # First name plus surname initial is common in match threads: "Bruno G.".
    if given and family:
        candidates.append(f"{given} {family[0]}.")

    # Compound surnames without particles ("Bruun Larsen", "Smith Rowe", "Mac Allister"):
    # split_name keeps only the final token, so add the two-word surname explicitly.
    all_parts = [p for p in folded.split(" ") if p]
    if (
        len(all_parts) >= 3
        and family
        and " " not in family
        and all_parts[-2].casefold() not in NAME_PARTICLES
    ):
        candidates.append(f"{all_parts[-2]} {all_parts[-1]}")

    # Individual words of a compound surname: "Nilsson Lindelof".
    # A surname that contains a particle is left whole, because splitting
    # "van Dijk" yields "Dijk", which matches the wrong player in a thread.
    if family and " " in family:
        parts = family.split(" ")
        has_particle = any(p.casefold() in NAME_PARTICLES for p in parts)
        if not has_particle:
            candidates.extend(parts)

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        cleaned = normalise_whitespace(candidate)
        if len(cleaned) < MIN_ALIAS_LENGTH:
            continue
        # Skip punctuation-only variants that collide with an existing form:
        # "B. Fernandes" and "B Fernandes" are one alias, not two.
        key = alias_key(cleaned)
        if not key or key in seen:
            continue
        # A bare generic surname cannot identify one player on its own.
        if key in GENERIC_SURNAMES:
            continue
        seen.add(key)
        ordered.append(cleaned)

    return ordered


def alias_key(text: str) -> str:
    """Matching key: accent-folded, lowercase, punctuation removed.

    Used to compare candidate text against the alias table, so the comparison
    is stable no matter how an author typed the name.
    """
    folded = strip_accents(text).casefold()
    return re.sub(r"[^a-z0-9 ]", "", folded).strip()


def ambiguous_aliases(alias_lists: dict[str, list[str]]) -> dict[str, list[str]]:
    """Find aliases claimed by more than one player.

    Parameters
    ----------
    alias_lists:
        Mapping of ``player_id`` to its alias list.

    Returns
    -------
    dict[str, list[str]]
        Alias key to the player ids that claim it. Only ambiguous entries.
    """
    claims: dict[str, list[str]] = {}
    for player_id, aliases in alias_lists.items():
        for alias in aliases:
            key = alias_key(alias)
            if not key:
                continue
            claims.setdefault(key, []).append(player_id)

    return {key: sorted(ids) for key, ids in claims.items() if len(ids) > 1}
