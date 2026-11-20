"""Stage E (person D): Skor Kualitas Teks, `player_summary`, candidate flags.

Reads  data/processed/text_analysis.parquet, texts_linked.parquet, text_sample.parquet
Writes data/processed/player_summary.parquet and candidates.csv

Skor Kualitas Teks (range -1..1), text only (AGENTS.md rule 6: numbers never form it):

    w_i   = source_weight * link_confidence * engagement_weight * aspect_boost
          (engagement_weight is 1.0 by default: likes/upvotes are not a quality signal)
    raw   = sum(w_i * s_i) / sum(w_i)                s_i = VADER compound of sentence i
    score = (sum(w_i * s_i) + k * prior) / (sum(w_i) + k)

`prior` is the weighted mean sentiment of the player's position group and `k` is
`scoring.confidence_shrinkage_k`: a player with little text is pulled toward his
position, so 3 comments cannot outrank 300. All sentences count (PRD §7 Stage D);
a sentence naming an aspect relevant to the player's position gets `aspect_boost`.

Things this module refuses to do silently:
  * unknown `source_group` raises, rather than getting weight 0;
  * buzz flags (`hidden_gem`, `overhyped`) stay empty when most players sit on
    the scrape quota, because a capped count has no rank (measured: 75% of players
    are exactly at 60 comments);
  * `undervalued_flag` stays empty until rating z-scores from A are supplied.

    python -m src.score.rank [--metrics PATH] [--buzz-counts CSV]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import ROOT, load_config

log = logging.getLogger("score.rank")
PROCESSED = ROOT / "data" / "processed"

PARAMS = {
    "aspect_boost": 1.5,  # sentence names an aspect relevant to the position
    "engagement_max_bonus": 0.0,  # OFF: C's handoff says likes are not a quality signal; 0.5 = up to +50%
    "engagement_cap": 100,  # score above this adds nothing; negatives count as 0
    "min_aspect_n": 3,  # fewer sentences than this: aspect not reported as "top"
    "buzz_usable_max_censored": 0.5,  # above this share at quota, buzz flags stay empty
}


def evidence_level(n_texts: int, scoring_cfg: dict) -> str:
    """AGENTS.md rule 8: <10 tidak cukup, 10-29 terbatas, >=30 cukup."""
    full = int(scoring_cfg["limited_texts_max"]) + 1
    if n_texts >= full:
        return "cukup"
    if n_texts >= int(scoring_cfg["min_texts"]):
        return "terbatas"
    return "tidak cukup"


def engagement_weight(engagement: pd.Series, params: dict) -> pd.Series:
    cap = params["engagement_cap"]
    clipped = engagement.fillna(0).clip(lower=0, upper=cap)
    return 1.0 + params["engagement_max_bonus"] * np.log1p(clipped) / np.log1p(cap)


def sentence_frame(
    analysis: pd.DataFrame, players: pd.DataFrame, scoring_cfg: dict, params: dict
) -> pd.DataFrame:
    """One row per sentence with its weight. `players` is indexed by player_id."""
    sent = analysis.drop_duplicates("text_id").set_index("text_id").copy()
    aspect_lists = analysis.dropna(subset=["aspect"]).groupby("text_id")["aspect"].agg(list)
    sent["aspects"] = [aspect_lists.get(t, []) for t in sent.index]
    sent["position_group"] = sent["player_id"].map(players["position_group"])
    if sent["position_group"].isna().any():
        raise ValueError("sentences for players missing from the player table")

    weights = scoring_cfg["source_weights"]
    unknown = set(sent["source_group"]) - set(weights)
    if unknown:
        raise ValueError(f"no source weight for {sorted(unknown)} in scoring.source_weights")
    relevance = scoring_cfg["position_relevance"]

    link = sent["link_confidence"].fillna(1.0) if "link_confidence" in sent else 1.0
    sent["w_base"] = sent["source_group"].map(weights) * link * engagement_weight(
        sent["engagement"], params
    )
    relevant = [
        bool(set(a) & set(relevance[g])) for a, g in zip(sent["aspects"], sent["position_group"])
    ]
    sent["relevant_aspect"] = relevant
    sent["w"] = sent["w_base"] * np.where(relevant, params["aspect_boost"], 1.0)
    return sent


def group_priors(sent: pd.DataFrame) -> pd.Series:
    """Weighted mean sentiment per position group, the shrinkage target."""
    weighted = sent.assign(ws=sent["w"] * sent["sentiment_score"])
    grouped = weighted.groupby("position_group")
    return grouped["ws"].sum() / grouped["w"].sum()


def shrunk(sum_ws: float, sum_w: float, prior: float, k: float) -> float:
    return (sum_ws + k * prior) / (sum_w + k)


def bootstrap_ci(
    w: np.ndarray, s: np.ndarray, prior: float, k: float, iterations: int, rng: np.random.Generator
) -> tuple[float, float]:
    """95% interval of the shrunk score, resampling the player's sentences."""
    n = len(w)
    if n == 0:
        return float("nan"), float("nan")
    idx = rng.integers(0, n, size=(iterations, n))
    sw, sws = w[idx].sum(axis=1), (w * s)[idx].sum(axis=1)
    draws = (sws + k * prior) / (sw + k)
    low, high = np.percentile(draws, [2.5, 97.5])
    return float(low), float(high)


def aspect_table(sent: pd.DataFrame) -> pd.DataFrame:
    """Per player and aspect: weighted mean sentiment and sentence count."""
    exploded = sent.explode("aspects").dropna(subset=["aspects"])
    exploded = exploded.assign(ws=exploded["w_base"] * exploded["sentiment_score"])
    grouped = exploded.groupby(["player_id", "aspects"])
    table = pd.DataFrame(
        {"mean": grouped["ws"].sum() / grouped["w_base"].sum(), "n": grouped.size()}
    )
    return table.reset_index().rename(columns={"aspects": "aspect"})


def top_aspects(table: pd.DataFrame, relevance: list[str], params: dict, top: int = 3) -> str:
    usable = table[table["aspect"].isin(relevance) & (table["n"] >= params["min_aspect_n"])]
    best = usable.sort_values(["mean", "n"], ascending=False).head(top)
    return "; ".join(f"{r.aspect}({r.mean:+.2f}, n={r.n})" for r in best.itertuples())


def percent_rank_within(df: pd.DataFrame, column: str, mask: pd.Series) -> pd.Series:
    """Percentile (0-100) of `column` inside each position group, over `mask` rows."""
    out = pd.Series(np.nan, index=df.index)
    subset = df[mask & df[column].notna()]
    out.loc[subset.index] = subset.groupby("position_group")[column].rank(pct=True) * 100
    return out


def buzz_censored(linked: pd.DataFrame, cfg: dict) -> pd.Series:
    """True when a source hit its per-player quota, so the count is a floor."""
    quotas = {
        group: int(src["max_texts_per_player"])
        for group, src in cfg["text_sources"].items()
        if isinstance(src, dict) and "max_texts_per_player" in src
    }
    comments = linked[linked["unit_type"] == "comment"]
    counts = comments.groupby(["player_id", "source_group"])["text_id"].nunique().unstack(fill_value=0)
    flags = pd.Series(False, index=counts.index)
    for group, quota in quotas.items():
        if group in counts:
            flags |= counts[group] >= quota
    return flags


def build_player_summary(
    analysis: pd.DataFrame,
    linked: pd.DataFrame,
    players: pd.DataFrame,
    cfg: dict,
    metrics: pd.DataFrame | None = None,
    buzz_counts: pd.Series | None = None,
    params: dict | None = None,
) -> pd.DataFrame:
    params = {**PARAMS, **(params or {})}
    scoring = cfg["scoring"]
    thr = cfg["thresholds"]
    k = float(scoring["confidence_shrinkage_k"])
    players = players.set_index("player_id", drop=False)

    sent = sentence_frame(analysis, players, scoring, params)
    priors = group_priors(sent)
    aspects = aspect_table(sent)

    comments = linked[linked["unit_type"] == "comment"]
    n_texts = comments.groupby("player_id")["text_id"].nunique()
    rng = np.random.default_rng(int(cfg["text_sample"]["random_seed"]))
    iterations = int(thr.get("bootstrap_iterations", 1000))

    rows = []
    for pid, player in players.iterrows():
        mine = sent[sent["player_id"] == pid]
        group = player["position_group"]
        prior = float(priors.get(group, 0.0))
        n = int(n_texts.get(pid, 0))
        row = {
            "player_id": pid,
            "season": cfg["league"]["season"],
            "name_canonical": player.get("name_canonical"),
            "position_group": group,
            "club": player.get("club"),
            "n_texts": n,
            "n_sentences": len(mine),
            "n_eff": float(mine["w"].sum()),
            "evidence_level": evidence_level(n, scoring),
            "market_value_eur": player.get("market_value_eur"),
        }
        if len(mine):
            sw, sws = float(mine["w"].sum()), float((mine["w"] * mine["sentiment_score"]).sum())
            low, high = bootstrap_ci(
                mine["w"].to_numpy(), mine["sentiment_score"].to_numpy(), prior, k, iterations, rng
            )
            row.update(
                text_quality_score=shrunk(sws, sw, prior, k),
                text_quality_raw=sws / sw,
                score_ci_low=low,
                score_ci_high=high,
                top_aspects=top_aspects(
                    aspects[aspects["player_id"] == pid], scoring["position_relevance"][group], params
                ),
            )
        rows.append(row)
    summary = pd.DataFrame(rows).set_index("player_id", drop=False)

    for name in aspects["aspect"].unique():
        part = aspects[aspects["aspect"] == name].set_index("player_id")
        summary[f"asp_{name}"] = part["mean"]
        summary[f"n_asp_{name}"] = part["n"]

    summary = _add_flags(summary, linked, cfg, metrics, buzz_counts, params)
    return summary.reset_index(drop=True)


def _above_median(summary: pd.DataFrame, metrics: pd.DataFrame | None) -> pd.Series:
    """Nullable boolean "rating above the position median". NA means *not validated*.

    Prefers `rating_above_median` from Stage A: A computes the median over the whole
    league population, which is a better yardstick than the median of 70 sampled
    players. Falls back to `rating_pos_zscore` against the sample's own median.
    A missing rating stays NA, never False (numeric_validation.md: the 10 sample
    players without a leaderboard rating are "tidak tervalidasi", not "below median").
    """
    none = pd.Series(pd.array([pd.NA] * len(summary), dtype="boolean"), index=summary.index)
    if metrics is None:
        summary["rating_pos_zscore"] = np.nan
        return none
    m = metrics.set_index("player_id")
    if "rating_pos_zscore" in m:
        summary["rating_pos_zscore"] = m["rating_pos_zscore"].reindex(summary.index)
    else:
        summary["rating_pos_zscore"] = np.nan
    if "rating_above_median" in m:
        return m["rating_above_median"].astype("boolean").reindex(summary.index)
    if "rating_pos_zscore" not in m:
        raise ValueError("metrics needs rating_above_median or rating_pos_zscore")
    z = summary["rating_pos_zscore"]
    medians = summary.groupby("position_group")["rating_pos_zscore"].transform("median")
    return (z > medians).astype("boolean").mask(z.isna())


def _add_flags(
    summary: pd.DataFrame,
    linked: pd.DataFrame,
    cfg: dict,
    metrics: pd.DataFrame | None,
    buzz_counts: pd.Series | None,
    params: dict,
) -> pd.DataFrame:
    thr = cfg["thresholds"]
    full = summary["evidence_level"] == "cukup"

    summary["text_quality_percentile"] = percent_rank_within(summary, "text_quality_score", full)
    summary["value_percentile"] = percent_rank_within(
        summary, "market_value_eur", pd.Series(True, index=summary.index)
    )
    summary["candidate_initial"] = (
        full
        & (summary["text_quality_percentile"] >= thr["text_quality_percentile"])
        & (summary["value_percentile"] <= thr["market_value_percentile"])
    )

    above = _above_median(summary, metrics)
    has_rating = bool(above.notna().any())
    candidate = summary["candidate_initial"].astype("boolean")
    # Unrated players are "not validated" (NA), whether or not they are candidates.
    summary["undervalued_flag"] = (candidate & above).mask(above.isna())
    if not has_rating:
        log.warning("no ratings supplied: undervalued_flag left empty")

    if buzz_counts is not None:
        summary["buzz_volume"] = buzz_counts.reindex(summary.index)
        censored = pd.Series(False, index=summary.index)
    else:
        summary["buzz_volume"] = summary["n_texts"]
        censored = buzz_censored(linked, cfg).reindex(summary.index, fill_value=False)
    summary["buzz_censored"] = censored

    evaluated = summary["n_texts"] > 0
    share = float(censored[evaluated].mean()) if evaluated.any() else 1.0
    usable = share < params["buzz_usable_max_censored"]
    summary["buzz_percentile"] = np.nan
    summary["hidden_gem_flag"] = pd.array([pd.NA] * len(summary), dtype="boolean")
    summary["overhyped_flag"] = pd.array([pd.NA] * len(summary), dtype="boolean")
    if usable:
        summary["buzz_percentile"] = percent_rank_within(summary, "buzz_volume", evaluated)
        if has_rating:
            low = (summary["buzz_percentile"] <= thr["buzz_percentile_hidden_gem"]).astype("boolean")
            high = (summary["buzz_percentile"] >= thr["buzz_percentile_overhyped"]).astype("boolean")
            summary["hidden_gem_flag"] = summary["undervalued_flag"] & low
            summary["overhyped_flag"] = high & ~above
    else:
        log.warning(
            "%.0f%% of players sit on the scrape quota: buzz is a floor, not a rank, so "
            "buzz_percentile and the hidden-gem/overhyped flags stay empty. Supply "
            "pre-quota counts with --buzz-counts to enable them.",
            100 * share,
        )
    return summary


def candidate_table(summary: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """The text+price shortlist, each row with its rating validation status.

    Validated rows (`undervalued_flag` True) are the findings; the others stay visible
    as "di bawah median" or "tidak ada rating" because a candidate that the numbers do
    not back is a result to report (AGENTS.md), not a row to drop.
    """
    short = summary[summary["candidate_initial"]].copy()
    flag = short["undervalued_flag"]
    short["validasi_rating"] = np.where(
        flag.isna(), "tidak ada rating", np.where(flag.fillna(False).astype(bool), "di atas median", "di bawah median")
    )
    cols = [
        "name_canonical", "club", "position_group", "text_quality_score", "score_ci_low", "score_ci_high",
        "market_value_eur", "rating_pos_zscore", "validasi_rating", "top_aspects", "n_texts", "evidence_level",
    ]
    return short.sort_values("text_quality_score", ascending=False).head(top_n)[cols]


def validation_rate(summary: pd.DataFrame) -> float | None:
    """PRD §11 main evidence metric: share of text-based candidates above median rating.

    Only candidates that *have* a rating count; unrated ones are reported separately.
    """
    cand = summary[summary["candidate_initial"] & summary["undervalued_flag"].notna()]
    if cand.empty:
        return None
    return float(cand["undervalued_flag"].astype(bool).mean())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage E: scores and candidates")
    parser.add_argument("--metrics", help="parquet with player_id, rating_pos_zscore (from A)")
    parser.add_argument("--buzz-counts", help="CSV player_id,raw_count (matches before the quota)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    cfg = load_config()
    analysis = pd.read_parquet(PROCESSED / "text_analysis.parquet")
    linked = pd.read_parquet(PROCESSED / "texts_linked.parquet")
    players = pd.read_parquet(ROOT / cfg["text_sample"]["locked_file"])
    metrics = pd.read_parquet(args.metrics) if args.metrics else None
    buzz = (
        pd.read_csv(args.buzz_counts).set_index("player_id")["raw_count"]
        if args.buzz_counts
        else None
    )

    summary = build_player_summary(analysis, linked, players, cfg, metrics, buzz)
    # Evidence first, before any score is looked at (AGENTS.md rule 16).
    log.info("evidence levels: %s", summary["evidence_level"].value_counts().to_dict())

    summary.to_parquet(PROCESSED / "player_summary.parquet", index=False)
    table = candidate_table(summary, int(cfg["output"]["top_n_candidates"]))
    table.to_csv(PROCESSED / "candidates.csv", index=False)
    rate = validation_rate(summary)
    unvalidated = int((summary["candidate_initial"] & summary["undervalued_flag"].isna()).sum())
    if unvalidated and metrics is not None:
        log.warning("%d text-based candidate(s) have no rating: not validated, kept out of the table", unvalidated)
    log.info(
        "candidates: %d | validation rate: %s",
        len(table),
        "n/a (no ratings)" if rate is None else f"{rate:.0%} (PRD §11 reads >=60% as useful)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())