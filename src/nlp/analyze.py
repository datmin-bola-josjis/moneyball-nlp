"""Stage D (person D): sentence sentiment and keyword aspects.

Input : data/processed/texts_linked.parquet  (from `python -m src.link.resolve`)
Output: data/processed/text_analysis.parquet (PRD §8 `text_analysis`)

One row per (sentence, aspect). A sentence with no aspect keyword has a single row
with `aspect` empty and `is_aspect_bearing` False: PRD §7 Stage D keeps those for
the overall sentiment. Anything that needs one row per sentence must first
`drop_duplicates("text_id")`.

Method limits to repeat in the report (AGENTS.md "Keterbatasan"):
  * VADER is lexicon-based: sarcasm and most slang are missed. The football
    lexicon below is a first guess, to be checked against the manual labels.
  * `aspect_sentiment` is the sentiment of the whole sentence, not of the clause
    holding the keyword, so a mixed sentence gives both aspects the same value.
  * Aspect keywords are matched as whole words. Substring matching would count
    "goalkeeper" as finishing; measured on 3,619 sentences it raised the aspect
    hit rate from 10.9% to 16.6%, mostly with false hits.
"""

from __future__ import annotations

import argparse
import logging
import re

import pandas as pd

from src.config import ROOT, load_config

log = logging.getLogger("nlp.analyze")
IN_FILE = ROOT / "data" / "processed" / "texts_linked.parquet"
OUT_FILE = ROOT / "data" / "processed" / "text_analysis.parquet"

# VADER scale is -4..4. "sick" and "mid" are left out on purpose: "sick" is
# praise as slang and a complaint about injuries, and "mid" collides with
# "midfielder". Extend only after looking at labelled errors.
FOOTBALL_LEXICON: dict[str, float] = {
    "world-class": 3.0,
    "worldclass": 3.0,
    "elite": 2.5,
    "classy": 2.0,
    "clinical": 2.0,
    "unreal": 2.5,
    "filthy": 2.5,
    "immense": 2.5,
    "unplayable": 2.5,
    "baller": 2.5,
    "beast": 2.5,
    "monster": 2.0,
    "underrated": 2.0,
    "wonderkid": 2.0,
    "cooked": -2.0,
    "washed": -2.0,
    "bottled": -2.0,
    "shocker": -2.5,
    "liability": -2.0,
    "passenger": -1.5,
    "overrated": -1.5,
    "sloppy": -1.5,
    "wasteful": -2.0,
    "flop": -2.5,
    "dross": -2.0,
}

MASK = "Player"


def build_analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon.update(FOOTBALL_LEXICON)
    return analyzer


def mask_alias(text: str, alias: str | None) -> str:
    """Replace the player's name so a name that looks like a word does not score.

    Whole-word only: masking "Mount" must not turn "amount" into "aPlayer".
    """
    if not alias:
        return text
    return re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", MASK, text, flags=re.IGNORECASE)


def compile_aspects(aspects: dict[str, list[str]]) -> dict[str, re.Pattern]:
    """Whole-word, case-insensitive pattern per aspect; spaces match space or hyphen."""
    compiled = {}
    for name, words in aspects.items():
        terms = sorted({w.strip().lower() for w in words if w.strip()}, key=len, reverse=True)
        body = "|".join(r"[\s-]+".join(re.escape(part) for part in t.split()) for t in terms)
        compiled[name] = re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE)
    return compiled


def find_aspects(text: str, patterns: dict[str, re.Pattern]) -> list[str]:
    return [name for name, pattern in patterns.items() if pattern.search(text)]


def sentiment_label(score: float, neutral_band: float) -> str:
    if score >= neutral_band:
        return "positive"
    if score <= -neutral_band:
        return "negative"
    return "neutral"


def analyze(
    sentences: pd.DataFrame,
    aspects: dict[str, list[str]],
    analyzer=None,
    neutral_band: float = 0.05,
) -> pd.DataFrame:
    """Score every sentence row. `sentences` must hold unit_type == 'sentence' only."""
    analyzer = analyzer or build_analyzer()
    patterns = compile_aspects(aspects)
    keep = [
        c
        for c in (
            "source",
            "source_group",
            "created_at",
            "engagement",
            "link_confidence",
            "parent_text_id",
        )
        if c in sentences.columns
    ]
    rows = []
    for rec in sentences.itertuples(index=False):
        text = rec.text_clean
        score = analyzer.polarity_scores(mask_alias(text, getattr(rec, "matched_alias", None)))[
            "compound"
        ]
        label = sentiment_label(score, neutral_band)
        found = find_aspects(text, patterns)
        base = {
            "text_id": rec.text_id,
            "player_id": rec.player_id,
            **{c: getattr(rec, c) for c in keep},
            "sentiment_label": label,
            "sentiment_score": score,
        }
        if found:
            rows.extend(
                {**base, "aspect": a, "aspect_sentiment": score, "is_aspect_bearing": True}
                for a in found
            )
        else:
            rows.append({**base, "aspect": None, "aspect_sentiment": None, "is_aspect_bearing": False})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage D: sentiment and aspects")
    parser.add_argument("--input", default=str(IN_FILE))
    parser.add_argument("--output", default=str(OUT_FILE))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    cfg = load_config()["nlp"]
    if cfg.get("sentiment_model") != "vader":
        raise SystemExit("only sentiment_model: vader is implemented (decisions.md 2026-11-11)")
    linked = pd.read_parquet(args.input)
    sentences = linked[linked["unit_type"] == "sentence"]
    log.info("scoring %d sentences", len(sentences))

    result = analyze(
        sentences, cfg["aspects"], neutral_band=float(cfg.get("min_confidence", 0.05))
    )
    per_sentence = result.drop_duplicates("text_id")
    log.info(
        "labels %s | aspect-bearing sentences %.1f%%",
        per_sentence["sentiment_label"].value_counts().to_dict(),
        100 * per_sentence["is_aspect_bearing"].mean(),
    )
    result.to_parquet(args.output, index=False)
    log.info("wrote %s (%d rows)", args.output, len(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())