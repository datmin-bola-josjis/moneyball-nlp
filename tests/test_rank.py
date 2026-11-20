"""Stage E: evidence labels, shrinkage, weights, flags."""

import numpy as np
import pandas as pd
import pytest

from src.score.rank import (
    PARAMS,
    build_player_summary,
    engagement_weight,
    evidence_level,
    sentence_frame,
    shrunk,
)

CFG = {
    "league": {"season": "2025/26"},
    "text_sample": {"random_seed": 1},
    "text_sources": {"reddit": {"max_texts_per_player": 60}},
    "scoring": {
        "source_weights": {"reddit": 1.0, "youtube": 0.8},
        "confidence_shrinkage_k": 10,
        "min_texts": 10,
        "limited_texts_max": 29,
        "position_relevance": {"FWD": ["finishing"], "DEF": ["defending"]},
    },
    "thresholds": {
        "text_quality_percentile": 75,
        "market_value_percentile": 40,
        "buzz_percentile_hidden_gem": 40,
        "buzz_percentile_overhyped": 75,
        "bootstrap_iterations": 50,
    },
}


@pytest.mark.parametrize(
    "n,label",
    [(0, "tidak cukup"), (9, "tidak cukup"), (10, "terbatas"), (29, "terbatas"), (30, "cukup")],
)
def test_evidence_level_boundaries(n, label):
    assert evidence_level(n, CFG["scoring"]) == label


def test_shrinkage_pulls_small_samples_toward_prior():
    few = shrunk(sum_ws=0.9 * 3, sum_w=3, prior=0.1, k=10)
    many = shrunk(sum_ws=0.9 * 300, sum_w=300, prior=0.1, k=10)
    assert 0.1 < few < many < 0.9
    assert many > 0.85 and few < 0.3


def test_engagement_is_off_by_default():
    assert (engagement_weight(pd.Series([-70, 0, 5, 100, 5000]), PARAMS) == 1.0).all()


def test_engagement_weight_is_bounded_and_ignores_negative():
    w = engagement_weight(pd.Series([-70, 0, 5, 100, 5000]), {**PARAMS, "engagement_max_bonus": 0.5})
    assert w.iloc[0] == w.iloc[1] == 1.0
    assert w.iloc[3] == w.iloc[4] == pytest.approx(1.5)
    assert w.is_monotonic_increasing


def _analysis(rows):
    return pd.DataFrame(rows)


def _row(tid, pid, score, source_group="reddit", aspect=None, link=1.0, eng=0):
    return {
        "text_id": tid, "player_id": pid, "source_group": source_group, "engagement": eng,
        "link_confidence": link, "sentiment_score": score, "aspect": aspect,
    }


def test_unknown_source_group_raises():
    analysis = _analysis([_row("t1", "p1", 0.5, source_group="tiktok")])
    players = pd.DataFrame({"player_id": ["p1"], "position_group": ["FWD"]}).set_index("player_id", drop=False)
    with pytest.raises(ValueError, match="tiktok"):
        sentence_frame(analysis, players, CFG["scoring"], PARAMS)


def test_aspect_boost_only_for_position_relevant_aspect():
    analysis = _analysis([
        _row("t1", "p1", 0.5, aspect="finishing"),
        _row("t2", "p1", 0.5, aspect="defending"),
        _row("t3", "p1", 0.5),
    ])
    players = pd.DataFrame({"player_id": ["p1"], "position_group": ["FWD"]}).set_index("player_id", drop=False)
    sent = sentence_frame(analysis, players, CFG["scoring"], PARAMS)
    assert sent.loc["t1", "w"] == pytest.approx(PARAMS["aspect_boost"])
    assert sent.loc["t2", "w"] == pytest.approx(1.0)
    assert sent.loc["t3", "w"] == pytest.approx(1.0)


def test_low_link_confidence_lowers_weight():
    analysis = _analysis([_row("t1", "p1", 0.5, link=0.2), _row("t2", "p1", 0.5, link=1.0)])
    players = pd.DataFrame({"player_id": ["p1"], "position_group": ["FWD"]}).set_index("player_id", drop=False)
    sent = sentence_frame(analysis, players, CFG["scoring"], PARAMS)
    assert sent.loc["t1", "w"] < sent.loc["t2", "w"]


def _world(n_players=8, texts=40):
    players, analysis, linked = [], [], []
    rng = np.random.default_rng(0)
    for i in range(n_players):
        pid = f"p{i}"
        players.append({"player_id": pid, "name_canonical": pid, "club": "X",
                        "position_group": "FWD", "market_value_eur": 1e6 * (i + 1)})
        for j in range(texts if i != 7 else 5):
            tid = f"{pid}_c{j}"
            linked.append({"text_id": tid, "player_id": pid, "unit_type": "comment", "source_group": "reddit"})
            analysis.append(_row(f"{tid}_s0", pid, float(np.clip(0.5 - 0.1 * i + rng.normal(0, 0.05), -1, 1))))  # cheap = praised
    return pd.DataFrame(players), pd.DataFrame(analysis), pd.DataFrame(linked)


def test_summary_marks_thin_evidence_and_keeps_it_out_of_candidates():
    players, analysis, linked = _world()
    s = build_player_summary(analysis, linked, players, CFG).set_index("player_id")
    assert s.loc["p7", "evidence_level"] == "tidak cukup"
    assert not s.loc["p7", "candidate_initial"]
    assert s.loc["p0", "evidence_level"] == "cukup"


def test_flags_stay_empty_without_ratings_and_when_buzz_is_capped():
    players, analysis, linked = _world(texts=60)  # everyone at the 60-comment quota
    s = build_player_summary(analysis, linked, players, CFG)
    assert s["undervalued_flag"].isna().all()
    assert s["hidden_gem_flag"].isna().all() and s["overhyped_flag"].isna().all()
    assert s["buzz_percentile"].isna().all()


def test_undervalued_needs_rating_above_position_median():
    players, analysis, linked = _world()
    # p0 is cheapest; give the top-scoring cheap player a rating above / below median
    base = build_player_summary(analysis, linked, players, CFG)
    cands = base[base["candidate_initial"]]["player_id"].tolist()
    assert cands, "the fixture must contain candidates or this test proves nothing"
    metrics = pd.DataFrame({"player_id": players["player_id"], "rating_pos_zscore": 0.0})
    metrics.loc[metrics["player_id"].isin(cands), "rating_pos_zscore"] = 1.0
    good = build_player_summary(analysis, linked, players, CFG, metrics=metrics)
    assert good.loc[good["candidate_initial"], "undervalued_flag"].astype(bool).all()
    metrics.loc[metrics["player_id"].isin(cands), "rating_pos_zscore"] = -1.0
    bad = build_player_summary(analysis, linked, players, CFG, metrics=metrics)
    assert not bad["undervalued_flag"].fillna(False).astype(bool).any()
    assert bad["undervalued_flag"].notna().all()  # rated players: False, never NA


def test_bootstrap_interval_contains_point_estimate_scale():
    players, analysis, linked = _world()
    s = build_player_summary(analysis, linked, players, CFG).set_index("player_id")
    row = s.loc["p3"]
    assert row["score_ci_low"] <= row["text_quality_score"] <= row["score_ci_high"]


def test_candidate_without_rating_is_not_validated_instead_of_false():
    players, analysis, linked = _world()
    base = build_player_summary(analysis, linked, players, CFG)
    cands = base[base["candidate_initial"]]["player_id"].tolist()
    assert cands
    metrics = pd.DataFrame({"player_id": players["player_id"], "rating_above_median": pd.array([True] * len(players), dtype="boolean")})
    metrics.loc[metrics["player_id"] == cands[0], "rating_above_median"] = pd.NA  # no leaderboard rating
    out = build_player_summary(analysis, linked, players, CFG, metrics=metrics).set_index("player_id")
    assert pd.isna(out.loc[cands[0], "undervalued_flag"])  # NA, not False
    assert all(out.loc[c, "undervalued_flag"] for c in cands[1:])


def test_rating_above_median_from_stage_a_wins_over_zscore():
    players, analysis, linked = _world()
    base = build_player_summary(analysis, linked, players, CFG)
    cands = base[base["candidate_initial"]]["player_id"].tolist()
    assert cands
    metrics = pd.DataFrame({"player_id": players["player_id"], "rating_pos_zscore": -5.0, "rating_above_median": False})
    metrics.loc[metrics["player_id"].isin(cands), "rating_above_median"] = True
    out = build_player_summary(analysis, linked, players, CFG, metrics=metrics)
    assert out.loc[out["candidate_initial"], "undervalued_flag"].astype(bool).all()


def test_metrics_without_a_rating_column_raises():
    players, analysis, linked = _world()
    with pytest.raises(ValueError, match="rating_above_median or rating_pos_zscore"):
        build_player_summary(analysis, linked, players, CFG, metrics=pd.DataFrame({"player_id": players["player_id"]}))


def test_shortlist_keeps_candidates_the_numbers_do_not_back():
    from src.score.rank import candidate_table

    players, analysis, linked = _world()
    base = build_player_summary(analysis, linked, players, CFG)
    cands = base[base["candidate_initial"]]["player_id"].tolist()
    assert len(cands) >= 2
    above = pd.array([True] * len(players), dtype="boolean")
    metrics = pd.DataFrame({"player_id": players["player_id"], "rating_above_median": above})
    metrics.loc[metrics["player_id"] == cands[0], "rating_above_median"] = False
    metrics.loc[metrics["player_id"] == cands[1], "rating_above_median"] = pd.NA
    table = candidate_table(build_player_summary(analysis, linked, players, CFG, metrics=metrics), 20)
    status = dict(zip(table["name_canonical"], table["validasi_rating"]))
    assert status[cands[0]] == "di bawah median" and status[cands[1]] == "tidak ada rating"
    assert set(status.values()) <= {"di atas median", "di bawah median", "tidak ada rating"}