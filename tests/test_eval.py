"""Labelling sheets and evaluation metrics."""

import math

import pandas as pd
import pytest

from src.eval.labeling import (
    SHEET_COLUMNS,
    build_gold,
    build_sheets,
    class_report,
    cohen_kappa,
    majority,
    parse_aspects,
    parse_link,
    parse_sentiment,
    wilson,
)


def _sentences(n=300):
    return pd.DataFrame(
        {
            "text_id": [f"t{i}" for i in range(n)],
            "player_id": [f"p{i % 7}" for i in range(n)],
            "pemain": [f"Player {i % 7}" for i in range(n)],
            "text_clean": [f"sentence number {i}" for i in range(n)],
            "konteks": ["context"] * n,
            "subreddit": ["x"] * n,
            "url": ["u"] * n,
            "link_confidence": [0.5] * n,
            "sentiment_score": [0.9] * n,
        }
    )


def test_sheets_share_overlap_and_split_the_rest():
    sheets, key = build_sheets(_sentences(), n=100, overlap=12, annotators=list("ABCD"), seed=1)
    assert all(len(s) == 12 + 22 for s in sheets.values())
    shared = set.intersection(*(set(s["item_id"]) for s in sheets.values()))
    assert len(shared) == 12
    own = [set(s["item_id"]) - shared for s in sheets.values()]
    assert sum(len(o) for o in own) == 88 and len(set.union(*own)) == 88  # no item twice


def test_25_each_when_n_is_64():
    sheets, _ = build_sheets(_sentences(), n=64, overlap=12, annotators=list("ABCD"), seed=1)
    assert all(len(s) == 25 for s in sheets.values())


def test_sheets_hide_every_machine_output():
    sheets, key = build_sheets(_sentences(), n=40, overlap=8, annotators=list("AB"), seed=1)
    for sheet in sheets.values():
        assert list(sheet.columns) == SHEET_COLUMNS
        assert "link_confidence" not in sheet and "sentiment_score" not in sheet
    assert "text_id" in key and "text_id" not in sheets["A"]


def test_sampling_is_reproducible_and_orders_differ():
    a1, _ = build_sheets(_sentences(), 40, 8, list("AB"), seed=5)
    a2, _ = build_sheets(_sentences(), 40, 8, list("AB"), seed=5)
    assert a1["A"]["item_id"].tolist() == a2["A"]["item_id"].tolist()
    shared = [i for i in a1["A"]["item_id"] if i in set(a1["B"]["item_id"])]
    assert shared != [i for i in a1["B"]["item_id"] if i in set(shared)]


def test_parsers_accept_indonesian_and_english():
    assert [parse_link(x) for x in ("Y", "tidak", "ragu", "", "maybe")] == ["y", "n", "ragu", None, None]
    assert [parse_sentiment(x) for x in ("positif", "NEG", "netral", "x")] == ["positive", "negative", "neutral", None]
    got, unknown = parse_aspects("Finishing; passing, bogus", {"finishing", "passing"})
    assert got == {"finishing", "passing"} and unknown == ["bogus"]
    assert parse_aspects("tidak ada", {"finishing"}) == (set(), [])


def test_majority_returns_none_on_tie():
    assert majority(["a", "a", "b"]) == "a"
    assert majority(["a", "b"]) is None
    assert majority([None, None]) is None


def test_cohen_kappa_known_values():
    assert cohen_kappa(list("aabb"), list("aabb")) == pytest.approx(1.0)
    assert cohen_kappa(list("aabb"), list("abab")) == pytest.approx(0.0)
    # hand-worked: po = 0.7, pe = 0.7*0.6 + 0.3*0.4 = 0.54, kappa = 0.16 / 0.46
    a = list("yyyyyyynnn")
    b = list("yyyyynnnny")
    assert cohen_kappa(a, b) == pytest.approx(0.16 / 0.46)
    assert math.isnan(cohen_kappa([None], [None]))


def test_class_report_values():
    rep = class_report(["a", "a", "b", "b"], ["a", "b", "b", "b"], ["a", "b"])
    assert rep["a"]["precision"] == 1.0 and rep["a"]["recall"] == 0.5
    assert rep["b"]["precision"] == pytest.approx(2 / 3)
    assert 0 < rep["macro_f1"] < 1


def test_wilson_interval_brackets_the_estimate():
    low, high = wilson(80, 100)
    assert low < 0.8 < high and high - low > 0.1
    assert all(math.isnan(x) for x in wilson(0, 0))


def test_gold_uses_majority_and_drops_ties():
    long = pd.DataFrame(
        [
            {"annotator": "A", "item_id": "L1", "filled": True, "link": "y", "sentiment": "positive", "aspects": {"finishing"}},
            {"annotator": "B", "item_id": "L1", "filled": True, "link": "y", "sentiment": "positive", "aspects": {"finishing"}},
            {"annotator": "C", "item_id": "L1", "filled": True, "link": "n", "sentiment": None, "aspects": set()},
            {"annotator": "A", "item_id": "L2", "filled": True, "link": "y", "sentiment": "positive", "aspects": set()},
            {"annotator": "B", "item_id": "L2", "filled": True, "link": "n", "sentiment": None, "aspects": set()},
        ]
    )
    gold = build_gold(long).set_index("item_id")
    assert gold.loc["L1", "gold_link"] == "y" and gold.loc["L1", "gold_sentiment"] == "positive"
    assert gold.loc["L1", "gold_aspects"] == {"finishing"}
    assert pd.isna(gold.loc["L2", "gold_link"])  # 1-1 tie stays unresolved


# ------------------------------------------------------------- team eval sheet
def _team_csv(path, rows):
    cols = ["eval_idx", "annotator_slot", "text_id", "player_id", "name_canonical", "club", "source",
            "matched_alias", "text_clean", "manual_link_ok", "manual_sentiment", "notes"]
    pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows]).to_csv(path, index=False, encoding="utf-8-sig")


def test_team_sheet_is_read_and_scored_end_to_end(tmp_path):
    from src.eval.labeling import build_gold, evaluate, read_team_sheets

    base = [
        {"eval_idx": 1, "annotator_slot": "ALL_4_OVERLAP", "text_id": "t1", "player_id": "p1"},
        {"eval_idx": 2, "annotator_slot": "A", "text_id": "t2", "player_id": "p1"},
        {"eval_idx": 3, "annotator_slot": "B", "text_id": "t3", "player_id": "p2"},
    ]
    a = [dict(base[0], manual_link_ok="y", manual_sentiment="positive"),
         dict(base[1], manual_link_ok="n"), base[2]]
    b = [dict(base[0], manual_link_ok="y", manual_sentiment="negative"), base[1],
         dict(base[2], manual_link_ok="yes", manual_sentiment="neutral")]
    _team_csv(tmp_path / "A.csv", a)
    _team_csv(tmp_path / "B.csv", b)
    long, key, expected = read_team_sheets([tmp_path / "A.csv", tmp_path / "B.csv"])
    assert expected == 1 * 2 + 2 and set(key["assigned"]) == {"ALL", "A", "B"}

    linked = pd.DataFrame({"text_id": ["t1", "t2", "t3"], "unit_type": "sentence", "link_confidence": 0.8,
                           "link_flags": "", "text_clean": ["x", "y", "z"]})
    analysis = pd.DataFrame({"text_id": ["t1", "t2", "t3"], "sentiment_label": ["positive", "positive", "neutral"],
                             "aspect": [None] * 3})
    res = evaluate(build_gold(long), key, linked, analysis, long, expected, aspects_labelled=False)
    assert res["aspects"] is None
    # E001 shared (y, y) -> y; E002 A only (n) -> n; E003 B only ("yes") -> y
    assert res["link"]["n"] == 3 and res["link"]["k"] == 2
    # sentiment: E001 positive/negative is a tie (dropped), E003 neutral matches the machine's neutral
    assert res["sentiment"]["n"] == 1 and res["sentiment"]["k"] == 1


def test_team_sheet_flags_unusable_values(tmp_path):
    from src.eval.labeling import read_team_sheets

    _team_csv(tmp_path / "A.csv", [
        {"eval_idx": 1, "annotator_slot": "A", "text_id": "t1", "player_id": "p1", "manual_link_ok": "mungkin"},
        {"eval_idx": 2, "annotator_slot": "A", "text_id": "t2", "player_id": "p1", "manual_link_ok": "y"},
    ])
    long, _, _ = read_team_sheets([tmp_path / "A.csv"])
    assert long.attrs["problems"] == {"manual_link_ok tidak dikenali": 1, "sentimen kosong pada baris y": 1}