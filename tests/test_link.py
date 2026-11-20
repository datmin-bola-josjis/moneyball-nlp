"""Stage C: dedupe, source grouping, link confidence."""

import pandas as pd
import pytest

from src.link.resolve import (
    alias_capitalisation,
    dedupe,
    link_features,
    other_capitalised,
    score_links,
    source_group,
)

OWNERS = {
    "kieran trippier": {"p_trip"},
    "trippier": {"p_trip"},
    "murphy": {"p_murph"},
    "elanga": {"p_elan"},
}


def test_source_group_maps_provider_names():
    assert source_group("reddit_arctic") == "reddit"
    assert source_group("youtube") == "youtube"
    with pytest.raises(ValueError):
        source_group("twitter")


def test_dedupe_keeps_same_comment_for_two_players():
    df = pd.DataFrame(
        {
            "text_id": ["a_p1", "a_p2", "b_p1"],
            "player_id": ["p1", "p2", "p1"],
            "text_clean_hash": ["h", "h", "h"],
            "unit_type": ["comment"] * 3,
            "source_group": ["reddit", "reddit", "youtube"],
        }
    )
    kept, dropped = dedupe(df)
    assert dropped == 1
    assert set(kept["text_id"]) == {"a_p1", "a_p2"}  # reddit wins, p2 untouched


def test_full_name_beats_bare_surname():
    full = link_features("Kieran Trippier delivered again", "Kieran Trippier", "p_trip", OWNERS)
    bare = link_features("Trippier delivered again", "Trippier", "p_trip", OWNERS)
    assert full["link_confidence"] > bare["link_confidence"]


def test_lowercase_only_mention_is_penalised():
    word = link_features("we should cash in now", "Cash", "p_cash", OWNERS)
    name = link_features("Cash was solid today", "Cash", "p_cash", OWNERS)
    assert "lowercase_only" in word["link_flags"]
    assert word["link_confidence"] < name["link_confidence"]


def test_sentence_start_capital_is_not_lowercase_only():
    assert alias_capitalisation("Cash was solid", "Cash") is True
    assert alias_capitalisation("we cash in", "Cash") is False
    assert alias_capitalisation("nothing here", "Cash") is None


def test_crowded_sentence_lowers_confidence():
    alone = link_features("Elanga was good today", "Elanga", "p_elan", OWNERS)
    crowd = link_features("Elanga was poor and Murphy should go, Willock too", "Elanga", "p_elan", OWNERS)
    assert crowd["link_confidence"] < alone["link_confidence"]
    assert "crowded" in crowd["link_flags"]


def test_other_capitalised_ignores_first_word_alias_and_I():
    assert other_capitalised("Elanga and I think Murphy is fine", "Elanga") == 1


def test_comment_inherits_best_sentence_confidence():
    df = pd.DataFrame(
        [
            {"text_id": "c1", "unit_type": "comment", "player_id": "p_elan", "text_clean": "x", "matched_alias": "Elanga", "parent_text_id": None},
            {"text_id": "c1_s0", "unit_type": "sentence", "player_id": "p_elan", "text_clean": "Elanga was good today", "matched_alias": "Elanga", "parent_text_id": "c1"},
            {"text_id": "c1_s1", "unit_type": "sentence", "player_id": "p_elan", "text_clean": "Elanga and Murphy and Willock and Kamara", "matched_alias": "Elanga", "parent_text_id": "c1"},
        ]
    )
    out = score_links(df, OWNERS).set_index("text_id")
    assert out.loc["c1", "link_confidence"] == out.loc["c1_s0", "link_confidence"]
    assert out.loc["c1_s1", "link_confidence"] < out.loc["c1_s0", "link_confidence"]