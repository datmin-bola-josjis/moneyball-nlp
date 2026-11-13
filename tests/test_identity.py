"""Tests for player identity and alias generation.

Alias bugs are silent: a missing alias means the scraper finds nothing for that
player and reports no error. These tests pin the cases that actually matter for
Premier League names.
"""

from __future__ import annotations

import pytest

from src.population.identity import (
    alias_key,
    ambiguous_aliases,
    generate_aliases,
    make_player_id,
    player_id_to_fotmob,
    split_name,
    strip_accents,
)


# --------------------------------------------------------------- player_id


def test_make_player_id() -> None:
    assert make_player_id(737066) == "fotmob_737066"


def test_player_id_roundtrip() -> None:
    assert player_id_to_fotmob(make_player_id(123)) == 123


# ------------------------------------------------------------------ negative


def test_non_numeric_id_rejected() -> None:
    with pytest.raises(ValueError):
        make_player_id("haaland")


def test_zero_id_rejected() -> None:
    with pytest.raises(ValueError):
        make_player_id(0)


def test_negative_id_rejected() -> None:
    with pytest.raises(ValueError):
        make_player_id(-5)


def test_wrong_prefix_rejected() -> None:
    with pytest.raises(ValueError):
        player_id_to_fotmob("haaland_9")


# ------------------------------------------------------------------- accents


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Šeško", "Sesko"),
        ("Guimarães", "Guimaraes"),
        ("Guéhi", "Guehi"),
        ("Højlund", "Hojlund"),
        ("Ødegaard", "Odegaard"),
        ("Łukasz", "Lukasz"),
        ("Đorđe", "Dorde"),
    ],
)
def test_strip_accents(raw: str, expected: str) -> None:
    assert strip_accents(raw) == expected


def test_odegaard_folds_to_ascii() -> None:
    """NFKD alone leaves Ø intact, so this would silently fail without the table."""
    aliases = generate_aliases("Martin Ødegaard")
    keys = {alias_key(alias) for alias in aliases}
    assert "odegaard" in keys


# -------------------------------------------------------------------- names


def test_particle_stays_with_surname() -> None:
    assert split_name("Virgil van Dijk") == ("Virgil", "van Dijk")


def test_particle_surname_is_not_split_into_bare_word() -> None:
    """"Dijk" alone would match the wrong player in a thread."""
    aliases = generate_aliases("Virgil van Dijk")
    assert "van Dijk" in aliases
    assert "Dijk" not in aliases


def test_compound_surname_without_particle_keeps_two_word_form() -> None:
    """Three-word names like 'Bruun Larsen' and 'Smith Rowe' need the compound surname."""
    assert "Bruun Larsen" in generate_aliases("Jacob Bruun Larsen")
    assert "Strand Larsen" in generate_aliases("Jørgen Strand Larsen")
    assert "Smith Rowe" in generate_aliases("Emile Smith Rowe")
    # Multi-particle names must not emit a clipped suffix like "de Ven".
    assert "de Ven" not in generate_aliases("Micky van de Ven")


def test_short_form_alias_present() -> None:
    """Threads write "Bruno G."; without this the scraper misses the text."""
    aliases = generate_aliases("Bruno Guimarães")
    assert "Bruno G." in aliases


def test_accented_name_has_ascii_alias() -> None:
    aliases = generate_aliases("Benjamin Šeško")
    assert "Sesko" in aliases


def test_single_word_name_does_not_crash() -> None:
    assert generate_aliases("Ronaldinho")


def test_empty_name_returns_empty_list() -> None:
    assert generate_aliases("") == []


# ----------------------------------------------------------------- boundary


def test_aliases_are_unique_by_match_key() -> None:
    aliases = generate_aliases("Bruno Fernandes")
    keys = [alias_key(alias) for alias in aliases]
    assert len(keys) == len(set(keys))


def test_generic_surname_alone_is_not_an_alias() -> None:
    """AGENTS.md rule 17: a bare "Silva" must not link to one player."""
    aliases = generate_aliases("Bernardo Silva")
    assert "Silva" not in aliases


def test_canonical_name_always_first() -> None:
    aliases = generate_aliases("Mohamed Salah")
    assert aliases[0] == "Mohamed Salah"


def test_ambiguity_detected_across_players() -> None:
    claims = ambiguous_aliases(
        {
            "fotmob_1": ["Bruno Fernandes", "Bruno F."],
            "fotmob_2": ["Bruno Guimaraes", "Bruno F."],
        }
    )
    assert "bruno f" in claims
    assert claims["bruno f"] == ["fotmob_1", "fotmob_2"]


def test_no_ambiguity_within_one_player() -> None:
    """One player must never collide with itself."""
    claims = ambiguous_aliases({"fotmob_1": generate_aliases("Bruno Fernandes")})
    assert claims == {}
