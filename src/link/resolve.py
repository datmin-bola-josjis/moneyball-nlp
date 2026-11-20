"""Stage C (person D): merge text sources, dedupe, and score how safe each link is.

Stage B already decides *which player a sentence names* (`AliasIndex.resolves`).
This module does not repeat that. It adds what B cannot see:

  * dedupe across sources, keyed on (text_clean_hash, player_id, unit_type),
    never on the hash alone: one comment legitimately names two sample players;
  * `source_group`: `reddit_arctic` -> `reddit`, so `scoring.source_weights`
    in config.yaml finds its key instead of silently missing;
  * `link_confidence` in (0, 1] per sentence, a weight and not a filter.

Why a confidence at all (measured on texts_reddit_full.jsonl, 3,619 sentences):
  * 94.7% of matches are a bare surname. Every one is "ambiguous" for
    AliasIndex, but all comments come from the player's own club subreddit,
    which counts as implicit club context, so the context check is always true
    here. It cannot separate "Cash" the player from "cash in on him".
  * 9.4% of sentences match only in lowercase; for "Cash" that was 22 of 55.
  * ~31% of sentences list several people ("Murphy should go, Willock..."), so
    a sentence-level sentiment can belong to someone else.

Input is `data/processed/texts_deduped.parquet` (Stage C dedupe across Reddit and
YouTube, see reports/dedupe.md), not the per-source jsonl files. The old jsonl
route read a Reddit-only file drawn from an earlier player sample, which dropped
41 of the 70 locked players and left YouTube out.

No sentence is dropped here by default (`link.min_confidence` = 0). A cut-off is
a threshold, so it is chosen against the manual labels and recorded in
docs/decisions.md (AGENTS.md rules 9 and 16). The weights below are first
guesses to be calibrated against those labels, not measured constants.

    python -m src.link.resolve [--input PATH]
"""

from __future__ import annotations

import argparse
import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

from src.config import ROOT, load_config
from src.scrape.aliases import normalize

log = logging.getLogger("link.resolve")
IN_FILE = ROOT / "data" / "processed" / "texts_deduped.parquet"
OUT_FILE = ROOT / "data" / "processed" / "texts_linked.parquet"

DEFAULTS = {
    "single_token_weight": 0.8,  # surname-only alias vs. full name
    "lowercase_weight": 0.4,  # single token seen only in lowercase ("cash in")
    "crowd_penalty": 0.5,  # per extra named entity in the sentence
    "min_confidence": 0.0,  # 0 = keep everything; set only from labelled data
}

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})
_CAP_WORD = re.compile(r"(?<![\w'])[A-Z][\w'-]*")
_PRONOUN_I = re.compile(r"^I(?:'[a-z]+)?$")
SOURCE_PRIORITY = {"reddit": 0, "youtube": 1, "article": 2}


# ----------------------------------------------------------------- sources
def source_group(source: str) -> str:
    """`reddit_arctic` / `reddit_apify` -> `reddit`; unknown names raise."""
    name = (source or "").lower()
    for group in SOURCE_PRIORITY:
        if name == group or name.startswith(group + "_"):
            return group
    raise ValueError(f"unknown text source {source!r}: add it to SOURCE_PRIORITY")


REQUIRED_COLUMNS = {
    "text_id", "player_id", "source", "unit_type", "text_clean",
    "text_clean_hash", "matched_alias", "parent_text_id",
}


def load_texts(path: Path) -> pd.DataFrame:
    """Read the deduped corpus and fail loudly if a column Stage C needs is missing."""
    df = pd.read_parquet(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise SystemExit(f"{path.name} lacks columns {sorted(missing)}")
    return df


def dedupe(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop repeats of the same text for the same player, earlier source wins."""
    ranked = df.assign(_rank=df["source_group"].map(SOURCE_PRIORITY)).sort_values(
        ["_rank", "text_id"], kind="stable"
    )
    kept = ranked.drop_duplicates(["text_clean_hash", "player_id", "unit_type"])
    return kept.drop(columns="_rank").sort_index(), len(df) - len(kept)


# ---------------------------------------------------------------- features
def _fold(text: str) -> str:
    """Remove accents but keep case, so capitalisation can still be read."""
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_APOSTROPHES))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def alias_capitalisation(text: str, alias: str | None) -> bool | None:
    """Is the alias written with a capital in `text`? None when it is not found.

    A capital at the start of a sentence says nothing, so those count as True:
    the penalty only fires on a lowercase-only mention.
    """
    if not alias:
        return None
    target = _fold(alias).split()
    if not target:
        return None
    pattern = r"(?<!\w)" + r"[\s-]+".join(re.escape(t) for t in target) + r"(?!\w)"
    match = re.search(pattern, _fold(text), re.IGNORECASE)
    return None if not match else match.group(0)[0].isupper()


def ngram_hits(text: str, alias_owners: dict[str, set[str]], max_n: int = 3) -> set[str]:
    """Player ids whose alias appears in `text` (1-3 word windows)."""
    tokens = normalize(text).split()
    found: set[str] = set()
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            owners = alias_owners.get(" ".join(tokens[i : i + n]))
            if owners:
                found |= owners
    return found


def other_capitalised(text: str, alias: str | None) -> int:
    """Capitalised words that are not the matched alias, "I", or the first word.

    A proxy for "how many other names are in this sentence". It also counts
    clubs and acronyms, so it over-counts a little; the label sample decides
    whether that matters.
    """
    folded = _fold(text).strip()
    skip = {t.lower() for t in _fold(alias or "").split()}
    count = 0
    for match in _CAP_WORD.finditer(folded):
        word = match.group(0)
        if match.start() == 0 or _PRONOUN_I.match(word):
            continue
        if word.lower().strip(".,'") in skip:
            continue
        count += 1
    return count


def link_features(
    text: str,
    alias: str | None,
    player_id: str,
    alias_owners: dict[str, set[str]],
    params: dict | None = None,
) -> dict:
    """Confidence in (0, 1] that this sentence's sentiment is about `player_id`."""
    p = {**DEFAULTS, **(params or {})}
    norm_alias = normalize(alias or "")
    multi_token = len(norm_alias.split()) > 1

    named_others = {pid for pid in ngram_hits(text, alias_owners) if pid != player_id}
    n_other = max(len(named_others), other_capitalised(text, alias))
    cap = alias_capitalisation(text, alias)

    specificity = 1.0 if multi_token else p["single_token_weight"]
    lowercase_only = (not multi_token) and cap is False
    case_factor = p["lowercase_weight"] if lowercase_only else 1.0
    crowd = 1.0 / (1.0 + p["crowd_penalty"] * n_other)

    flags = []
    if lowercase_only:
        flags.append("lowercase_only")
    if n_other >= 2:
        flags.append("crowded")
    return {
        "link_confidence": round(specificity * case_factor * crowd, 3),
        "link_n_other": n_other,
        "link_flags": ",".join(flags),
    }


def score_links(
    df: pd.DataFrame, alias_owners: dict[str, set[str]], params: dict | None = None
) -> pd.DataFrame:
    """Add link columns. Sentences get their own score; a comment gets its best."""
    out = df.copy()
    out["link_confidence"] = float("nan")
    out["link_n_other"] = pd.array([pd.NA] * len(out), dtype="Int64")
    out["link_flags"] = ""

    is_sentence = out["unit_type"] == "sentence"
    for idx in out.index[is_sentence]:
        row = out.loc[idx]
        feats = link_features(
            row["text_clean"], row["matched_alias"], row["player_id"], alias_owners, params
        )
        for key, value in feats.items():
            out.at[idx, key] = value

    best = out.loc[is_sentence].groupby("parent_text_id")["link_confidence"].max()
    is_comment = out["unit_type"] == "comment"
    out.loc[is_comment, "link_confidence"] = out.loc[is_comment, "text_id"].map(best)
    return out


def apply_min_confidence(df: pd.DataFrame, minimum: float) -> pd.DataFrame:
    """Drop sentences below `minimum`. A no-op at 0, which is the default."""
    if minimum <= 0:
        return df
    weak = (df["unit_type"] == "sentence") & (df["link_confidence"] < minimum)
    return df.loc[~weak]


# --------------------------------------------------------------------- run
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage C: dedupe and link confidence")
    parser.add_argument("--input", default=str(IN_FILE), help="deduped corpus parquet")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    from src.scrape.aliases import AliasIndex  # imported late: needs the player table
    from src.scrape.players import load_players

    cfg = load_config()
    params = {**DEFAULTS, **cfg.get("link", {})}

    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make dedupe` (Stage C) first")
    df = load_texts(path)
    log.info("reading %s (%d rows)", path.name, len(df))
    df["source_group"] = df["source"].map(source_group)
    log.info("rows by source: %s", df["source_group"].value_counts().to_dict())
    if "youtube" not in set(df["source_group"]):
        log.warning("no YouTube texts yet: every score below is Reddit-only")

    sample = load_players(ROOT / cfg["text_sample"]["locked_file"])
    index = AliasIndex.build(sample)
    unknown = set(df["player_id"]) - set(index.players)
    if unknown:
        log.warning("%d player_ids not in the locked sample are dropped", len(unknown))
        df = df[df["player_id"].isin(index.players)]

    df, dropped = dedupe(df)
    log.info("dedupe removed %d repeated (hash, player, unit) rows", dropped)

    alias_owners = {k: v for k, v in index.alias_owners.items() if len(k) >= 3}
    df = score_links(df, alias_owners, params)
    df = apply_min_confidence(df, float(params["min_confidence"]))

    sent = df[df["unit_type"] == "sentence"]
    log.info(
        "sentences %d, link_confidence quartiles %s, lowercase_only %d, crowded %d",
        len(sent),
        sent["link_confidence"].quantile([0.25, 0.5, 0.75]).round(2).tolist(),
        sent["link_flags"].str.contains("lowercase_only").sum(),
        sent["link_flags"].str.contains("crowded").sum(),
    )
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_FILE, index=False)
    log.info("wrote %s (%d rows)", OUT_FILE, len(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())