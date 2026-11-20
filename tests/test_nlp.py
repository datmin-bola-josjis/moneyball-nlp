"""Stage D NLP: aspect matching, name masking, sentiment labels."""

import pandas as pd
import pytest

pytest.importorskip("vaderSentiment")

from src.nlp.analyze import (  # noqa: E402
    analyze,
    build_analyzer,
    compile_aspects,
    find_aspects,
    mask_alias,
    sentiment_label,
)

ASPECTS = {
    "finishing": ["finish", "goal", "goals", "header", "tap-in"],
    "stamina": ["work rate", "engine"],
    "defending": ["block", "tackle"],
}


def test_aspect_keywords_match_whole_words_only():
    patterns = compile_aspects(ASPECTS)
    assert find_aspects("Great goalkeeper and a good goalpost", patterns) == []
    assert find_aspects("He scores goals for fun", patterns) == ["finishing"]
    assert find_aspects("A road block ahead", patterns) == ["defending"]


def test_multiword_and_hyphenated_keywords():
    patterns = compile_aspects(ASPECTS)
    assert find_aspects("His work-rate is huge", patterns) == ["stamina"]
    assert find_aspects("Easy tap-in for him", patterns) == ["finishing"]


def test_sentence_can_carry_several_aspects():
    patterns = compile_aspects(ASPECTS)
    found = find_aspects("Great header and a big tackle", patterns)
    assert sorted(found) == ["defending", "finishing"]


def test_mask_alias_is_whole_word():
    assert mask_alias("An amount of Mount's work", "Mount") == "An amount of Player's work"
    assert mask_alias("Anything", None) == "Anything"


def test_sentiment_label_uses_neutral_band():
    assert sentiment_label(0.30, 0.05) == "positive"
    assert sentiment_label(-0.30, 0.05) == "negative"
    assert sentiment_label(0.01, 0.05) == "neutral"


def test_football_slang_changes_polarity():
    analyzer = build_analyzer()
    assert analyzer.polarity_scores("He was absolutely filthy today")["compound"] > 0.3
    assert analyzer.polarity_scores("He is completely washed")["compound"] < -0.2


def test_player_name_does_not_leak_into_sentiment():
    analyzer = build_analyzer()
    plain = analyzer.polarity_scores("Player was fine")["compound"]
    frame = pd.DataFrame(
        [
            {
                "text_id": "t1",
                "player_id": "p1",
                "text_clean": "Cash was fine",
                "matched_alias": "Cash",
            }
        ]
    )
    out = analyze(frame, ASPECTS, analyzer)
    assert out.loc[0, "sentiment_score"] == pytest.approx(plain)


def test_analyze_emits_one_row_per_aspect_and_one_for_none():
    frame = pd.DataFrame(
        [
            {"text_id": "a", "player_id": "p1", "text_clean": "Great header and a big tackle", "matched_alias": None},
            {"text_id": "b", "player_id": "p1", "text_clean": "Decent game overall today", "matched_alias": None},
        ]
    )
    out = analyze(frame, ASPECTS, build_analyzer())
    assert (out["text_id"] == "a").sum() == 2
    row_b = out[out["text_id"] == "b"].iloc[0]
    assert not row_b["is_aspect_bearing"] and pd.isna(row_b["aspect"])