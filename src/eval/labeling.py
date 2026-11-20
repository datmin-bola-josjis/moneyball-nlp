"""Manual labelling sheets and the PRD §11 evaluation (person D).

    python -m src.eval.labeling sheet [--n 100] [--overlap 12] [--annotators A,B,C,D]
    python -m src.eval.labeling score [--labels-dir data/interim/labels]

`sheet` draws a uniform random sample of sentences (seed = text_sample.random_seed,
AGENTS.md rule 13) and writes one CSV per annotator. The first `overlap` sentences go
to everybody, so Cohen's kappa can be computed; the rest are split between people.
The sheets show the sentence, its comment and the player's name, and hide every
machine output (VADER score, aspect, link_confidence), so labelling is not anchored
on what the model said. The key linking items back to texts stays in `_key.csv`.

`score` reads the filled sheets and writes reports/evaluasi_pemodelan.md:
linking precision, sentiment accuracy and macro-F1, keyword-aspect precision and
recall, kappa, and the wrong examples AGENTS.md asks for.

What cannot be measured here: linking *recall*. Sentences that Stage B dropped never
reach the sample, so only precision of the kept links is reported.

Sample size note: `--n 100 --overlap 12` gives 100 distinct sentences, 34 per person
(12 shared + 22 own). If the team keeps "25 per person", use `--n 64`: 12 shared +
13 own = 25 each, but only 64 distinct sentences, which widens every interval.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd

from src.config import ROOT, load_config

log = logging.getLogger("eval.labeling")
PROCESSED = ROOT / "data" / "processed"
LABELS_DIR = ROOT / "data" / "interim" / "labels"
REPORT = ROOT / "reports" / "evaluasi_pemodelan.md"

LABEL_COLUMNS = ["membahas_pemain", "sentimen", "aspek", "catatan"]
SHEET_COLUMNS = [
    "item_id", "pemain", "kalimat", "konteks_komentar", "subreddit", "url", *LABEL_COLUMNS,
]
LINK_TARGET = 0.85  # PRD §11
SENTIMENT_TARGET = 0.75  # PRD §11
SENTIMENTS = ["positive", "neutral", "negative"]

_YES, _NO, _UNSURE = {"y", "ya", "yes", "1", "true"}, {"n", "tidak", "no", "0", "false"}, {"ragu", "?", "unsure"}
_SENT = {
    "pos": "positive", "positif": "positive", "positive": "positive", "+": "positive",
    "neu": "neutral", "netral": "neutral", "neutral": "neutral", "0": "neutral",
    "neg": "negative", "negatif": "negative", "negative": "negative", "-": "negative",
}


# ------------------------------------------------------------------ sheets
def build_sheets(
    sentences: pd.DataFrame, n: int, overlap: int, annotators: list[str], seed: int
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Return one DataFrame per annotator plus the key (item -> text_id, owner)."""
    if overlap > n:
        raise ValueError("overlap cannot exceed n")
    picked = sentences.sample(n=min(n, len(sentences)), random_state=seed).reset_index(drop=True)
    picked["item_id"] = [f"L{i + 1:03d}" for i in range(len(picked))]

    shared = set(picked["item_id"][:overlap])
    owner = {
        iid: annotators[i % len(annotators)] for i, iid in enumerate(picked["item_id"][overlap:])
    }
    picked["assigned"] = [("ALL" if i in shared else owner[i]) for i in picked["item_id"]]

    sheets = {}
    for pos, who in enumerate(annotators):
        mine = picked[picked["assigned"].isin(["ALL", who])]
        mine = mine.sample(frac=1, random_state=seed + pos)  # own order: no order effects
        sheet = pd.DataFrame(
            {
                "item_id": mine["item_id"],
                "pemain": mine["pemain"],
                "kalimat": mine["text_clean"],
                "konteks_komentar": mine["konteks"].str.slice(0, 600),
                "subreddit": mine["subreddit"],
                "url": mine["url"],
            }
        )
        for col in LABEL_COLUMNS:
            sheet[col] = ""
        sheets[who] = sheet[SHEET_COLUMNS]
    key = picked[["item_id", "text_id", "player_id", "assigned"]]
    return sheets, key


def load_sentences(linked_path: Path, sample_path: Path) -> pd.DataFrame:
    linked = pd.read_parquet(linked_path)
    comments = linked[linked["unit_type"] == "comment"].set_index("text_id")["text_clean"]
    sent = linked[linked["unit_type"] == "sentence"].copy()
    sent["konteks"] = sent["parent_text_id"].map(comments).fillna("")
    names = pd.read_parquet(sample_path).set_index("player_id")["name_canonical"]
    sent["pemain"] = sent["player_id"].map(names).fillna(sent["player_id"])
    return sent


def _has_labels(directory: Path) -> bool:
    for path in directory.glob("label_*.csv"):
        frame = _read_csv(path)
        if any(frame[c].astype(str).str.strip().ne("").any() for c in LABEL_COLUMNS if c in frame):
            return True
    return False


def write_sheets(sheets: dict[str, pd.DataFrame], key: pd.DataFrame, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if _has_labels(directory):
        raise SystemExit(f"{directory} already holds filled labels; move it first. Nothing written.")
    for who, sheet in sheets.items():
        # utf-8-sig so Excel reads accents (Ødegaard, Šeško) correctly.
        sheet.to_csv(directory / f"label_{who}.csv", index=False, encoding="utf-8-sig")
    key.to_csv(directory / "_key.csv", index=False)


# ----------------------------------------------------------------- parsing
def _read_csv(path: Path) -> pd.DataFrame:
    """Excel with an Indonesian locale saves ';' instead of ','; sniff the delimiter."""
    return pd.read_csv(path, sep=None, engine="python", dtype=str, keep_default_na=False,
                       encoding="utf-8-sig")


def _read_table(path: Path) -> pd.DataFrame:
    """A filled sheet: CSV (any delimiter) or the "Lembar" tab of an .xlsx (needs openpyxl)."""
    if path.suffix.lower() == ".xlsx":
        return pd.read_excel(path, sheet_name="Lembar", dtype=str).fillna("")
    return _read_csv(path)


def parse_link(value: str) -> str | None:
    raw = (value or "").strip().lower()
    return "y" if raw in _YES else "n" if raw in _NO else "ragu" if raw in _UNSURE else None


def parse_sentiment(value: str) -> str | None:
    return _SENT.get((value or "").strip().lower())


def parse_aspects(value: str, known: set[str]) -> tuple[set[str], list[str]]:
    """Return (recognised aspects, unrecognised words). Empty/'tidak ada' = no aspect."""
    parts = [p.strip().lower() for p in re.split(r"[;,|]", value or "") if p.strip()]
    parts = [p for p in parts if p not in {"tidak ada", "none", "-", "tidak"}]
    return {p for p in parts if p in known}, [p for p in parts if p not in known]


def read_labels(directory: Path, annotators: list[str], known_aspects: set[str]) -> pd.DataFrame:
    """Long table: annotator, item_id, link, sentiment, aspects, plus parse problems."""
    rows, problems = [], Counter()
    for who in annotators:
        path = directory / f"label_{who}.xlsx"
        if not path.exists():
            path = directory / f"label_{who}.csv"
        if not path.exists():
            log.warning("missing label_%s (.xlsx or .csv)", who)
            continue
        for rec in _read_table(path).to_dict("records"):
            link, sentiment = parse_link(rec["membahas_pemain"]), parse_sentiment(rec["sentimen"])
            aspects, unknown = parse_aspects(rec["aspek"], known_aspects)
            filled = bool(str(rec["membahas_pemain"]).strip())
            if filled and link is None:
                problems["membahas_pemain tidak dikenali"] += 1
            if link == "y" and str(rec["sentimen"]).strip() and sentiment is None:
                problems["sentimen tidak dikenali"] += 1
            problems["aspek tidak dikenali"] += len(unknown)
            rows.append(
                {"annotator": who, "item_id": rec["item_id"], "filled": filled, "link": link,
                 "sentiment": sentiment, "aspects": aspects}
            )
    out = pd.DataFrame(rows)
    out.attrs["problems"] = dict(problems)
    return out


# ----------------------------------------------------------------- metrics
def majority(values: list) -> object | None:
    """Most common value; None on a tie or an empty list (an unresolved item)."""
    counts = Counter(v for v in values if v is not None).most_common()
    if not counts or (len(counts) > 1 and counts[0][1] == counts[1][1]):
        return None
    return counts[0][0]


def cohen_kappa(a: list, b: list) -> float:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        return float("nan")
    observed = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    expected = sum(ca[k] / n * cb[k] / n for k in set(ca) | set(cb))
    return float("nan") if expected == 1 else (observed - expected) / (1 - expected)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion; a 100-item sample is wide, say so."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def class_report(gold: list[str], pred: list[str], labels: list[str]) -> dict:
    out = {}
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"precision": prec, "recall": rec, "f1": f1, "support": sum(g == lab for g in gold)}
    out["macro_f1"] = sum(out[lab]["f1"] for lab in labels) / len(labels)
    return out


def pairwise_kappa(long: pd.DataFrame, column: str) -> list[float]:
    wide = long.pivot(index="item_id", columns="annotator", values=column)
    return [
        k for a, b in combinations(wide.columns, 2)
        if not math.isnan(k := cohen_kappa(wide[a].tolist(), wide[b].tolist()))
    ]


# ------------------------------------------------------------------- score
def build_gold(long: pd.DataFrame) -> pd.DataFrame:
    """One row per item: gold link, gold sentiment, gold aspects (majority rules)."""
    rows = []
    for item, grp in long[long["filled"]].groupby("item_id"):
        link = majority([v for v in grp["link"] if v in {"y", "n"}])
        sentiment = majority(list(grp["sentiment"])) if link == "y" else None
        counts = Counter(a for s in grp["aspects"] for a in s)
        aspects = {a for a, c in counts.items() if c > len(grp) / 2}
        rows.append({"item_id": item, "gold_link": link, "gold_sentiment": sentiment,
                     "gold_aspects": aspects, "n_labels": len(grp)})
    return pd.DataFrame(rows)


def evaluate(gold: pd.DataFrame, key: pd.DataFrame, linked: pd.DataFrame, analysis: pd.DataFrame,
             long: pd.DataFrame, expected_pairs: int, aspects_labelled: bool = True) -> dict:
    """All numbers behind the report, so tests can check them without parsing markdown."""
    sent_cols = linked[linked["unit_type"] == "sentence"].set_index("text_id")[
        ["link_confidence", "link_flags", "text_clean"]
    ]
    per_sentence = analysis.drop_duplicates("text_id").set_index("text_id")["sentiment_label"]
    machine_aspects = analysis.dropna(subset=["aspect"]).groupby("text_id")["aspect"].agg(set)

    df = gold.merge(key, on="item_id").join(sent_cols, on="text_id")
    df["pred_sentiment"] = df["text_id"].map(per_sentence)
    df["pred_aspects"] = [machine_aspects.get(t, set()) for t in df["text_id"]]

    out = {"labelled_pairs": int(long["filled"].sum()), "expected_pairs": expected_pairs,
           "items_with_gold_link": int(df["gold_link"].notna().sum()),
           "unresolved_items": int(df["gold_link"].isna().sum()), "problems": long.attrs.get("problems", {})}

    judged = df[df["gold_link"].isin(["y", "n"])]
    k, n = int((judged["gold_link"] == "y").sum()), len(judged)
    out["link"] = {"precision": k / n if n else float("nan"), "k": k, "n": n, "ci": wilson(k, n)}
    bands = pd.cut(judged["link_confidence"], [-0.01, 0.4, 0.7, 1.01], labels=["<0.4", "0.4-0.7", ">=0.7"])
    out["link_by_band"] = {str(b): (int((g["gold_link"] == "y").sum()), len(g)) for b, g in judged.groupby(bands, observed=True)}
    flags = judged["link_flags"].replace("", "none")
    out["link_by_flag"] = {f: (int((g["gold_link"] == "y").sum()), len(g)) for f, g in judged.groupby(flags)}
    out["link_cut_simulation"] = {}
    for cut in (0.2, 0.4, 0.6):
        kept = judged[judged["link_confidence"] >= cut]
        out["link_cut_simulation"][cut] = {
            "kept": len(kept), "of": n,
            "precision": float((kept["gold_link"] == "y").mean()) if len(kept) else float("nan"),
        }

    sent = df[(df["gold_link"] == "y") & df["gold_sentiment"].notna() & df["pred_sentiment"].notna()]
    gold_s, pred_s = sent["gold_sentiment"].tolist(), sent["pred_sentiment"].tolist()
    ks = sum(g == p for g, p in zip(gold_s, pred_s))
    base = Counter(gold_s).most_common(1)[0] if gold_s else ("-", 0)
    out["sentiment"] = {
        "accuracy": ks / len(sent) if len(sent) else float("nan"), "k": ks, "n": len(sent),
        "ci": wilson(ks, len(sent)), "majority_class": base[0],
        "majority_accuracy": base[1] / len(sent) if len(sent) else float("nan"),
        "report": class_report(gold_s, pred_s, SENTIMENTS) if len(sent) else {},
        "confusion": Counter(zip(gold_s, pred_s)),
    }

    out["aspects"] = None
    if aspects_labelled:
        asp = df[df["gold_link"] == "y"]
        tp = sum(len(g & p) for g, p in zip(asp["gold_aspects"], asp["pred_aspects"]))
        fp = sum(len(p - g) for g, p in zip(asp["gold_aspects"], asp["pred_aspects"]))
        fn = sum(len(g - p) for g, p in zip(asp["gold_aspects"], asp["pred_aspects"]))
        prec, rec = tp / (tp + fp) if tp + fp else float("nan"), tp / (tp + fn) if tp + fn else float("nan")
        out["aspects"] = {"precision": prec, "recall": rec, "tp": tp, "fp": fp, "fn": fn, "n": len(asp),
                          "support": Counter(a for s in asp["gold_aspects"] for a in s)}

    shared = long[long["item_id"].isin(key.loc[key["assigned"] == "ALL", "item_id"])]
    for name, col in (("kappa_link", "link"), ("kappa_sentiment", "sentiment")):
        ks_ = pairwise_kappa(shared[shared["filled"]], col) if len(shared) else []
        out[name] = {"mean": sum(ks_) / len(ks_) if ks_ else float("nan"), "pairs": len(ks_),
                     "min": min(ks_) if ks_ else float("nan"), "max": max(ks_) if ks_ else float("nan")}
    out["frame"] = df
    return out


def _snip(text: str, width: int = 200) -> str:
    return " ".join(str(text).split())[:width]


def write_report(res: dict, path: Path) -> Path:
    link, sent, asp = res["link"], res["sentiment"], res["aspects"]
    complete = res["labelled_pairs"] >= res["expected_pairs"] and not res["unresolved_items"]
    pct = lambda x: "n/a" if x != x else f"{x:.1%}"  # noqa: E731
    ok = lambda v, t: "tercapai" if v >= t else "belum tercapai"  # noqa: E731
    lines = [
        "# Evaluasi Pemodelan (Tahap D)", "",
        f"- Status data: **{'LENGKAP' if complete else 'SEMENTARA'}** — {res['labelled_pairs']} dari "
        f"{res['expected_pairs']} label terisi, {res['unresolved_items']} kalimat tanpa keputusan mayoritas",
        f"- Masalah baca: {res['problems'] or 'tidak ada'}", "",
        "## Entity linking (presisi; recall tidak terukur karena kalimat yang dibuang B tidak ikut sampel)", "",
        f"- Presisi: **{pct(link['precision'])}** ({link['k']}/{link['n']}), 95% CI "
        f"{pct(link['ci'][0])}–{pct(link['ci'][1])}; target PRD §11 ≥ {LINK_TARGET:.0%}: "
        f"**{ok(link['precision'], LINK_TARGET) if link['n'] else 'n/a'}**", "",
        "| Kelompok | Benar | Total | Presisi |", "|---|---|---|---|",
    ]
    for name, table in (("link_confidence", res["link_by_band"]), ("flag", res["link_by_flag"])):
        for label, (k, n) in table.items():
            lines.append(f"| {name} {label} | {k} | {n} | {pct(k / n if n else float('nan'))} |")
    lines += ["", "Simulasi pemotongan (informasi saja; ambang dipilih tim, lalu dicatat di decisions.md):", "",
              "| min_confidence | Kalimat tersisa | Presisi |", "|---|---|---|"]
    for cut, v in res["link_cut_simulation"].items():
        lines.append(f"| {cut} | {v['kept']}/{v['of']} | {pct(v['precision'])} |")

    lines += ["", "## Sentimen (VADER + lexicon bola), hanya kalimat yang benar membahas pemain", "",
              f"- Akurasi: **{pct(sent['accuracy'])}** ({sent['k']}/{sent['n']}), 95% CI "
              f"{pct(sent['ci'][0])}–{pct(sent['ci'][1])}; target ≥ {SENTIMENT_TARGET:.0%}: "
              f"**{ok(sent['accuracy'], SENTIMENT_TARGET) if sent['n'] else 'n/a'}**",
              f"- Pembanding: selalu menebak '{sent['majority_class']}' akan benar {pct(sent['majority_accuracy'])}",
              f"- Macro-F1: {sent['report'].get('macro_f1', float('nan')):.3f}", "",
              "| Kelas | Presisi | Recall | F1 | Jumlah gold |", "|---|---|---|---|---|"]
    for lab in SENTIMENTS:
        r = sent["report"].get(lab)
        if r:
            lines.append(f"| {lab} | {r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} | {r['support']} |")
    lines += ["", "Matriks kebingungan (baris = label manual, kolom = mesin):", "",
              "| gold \\ mesin | " + " | ".join(SENTIMENTS) + " |", "|---|---|---|---|"]
    for g in SENTIMENTS:
        lines.append(f"| {g} | " + " | ".join(str(sent["confusion"].get((g, p), 0)) for p in SENTIMENTS) + " |")

    if asp is None:
        lines += ["", "## Aspek", "", "- Tidak dinilai: lembar ini tidak memuat label aspek.", ""]
    else:
        lines += ["", "## Aspek (kamus kata kunci, kata utuh)", "",
                  f"- Presisi {pct(asp['precision'])}, recall {pct(asp['recall'])} (TP {asp['tp']}, FP {asp['fp']}, "
                  f"FN {asp['fn']}) pada {asp['n']} kalimat",
                  f"- Jumlah aspek per label manual: {dict(asp['support']) or 'tidak ada'}", ""]
    lines += ["## Kesepakatan antar-anotator (kalimat overlap)", ""]
    for name, label in (("kappa_link", "membahas pemain"), ("kappa_sentiment", "sentimen")):
        k = res[name]
        lines.append(f"- Cohen's κ {label}: rata-rata {k['mean']:.2f} dari {k['pairs']} pasangan "
                     f"(min {k['min']:.2f}, maks {k['max']:.2f})")

    df = res["frame"]
    bad_sent = df[(df["gold_link"] == "y") & df["gold_sentiment"].notna()
                  & (df["gold_sentiment"] != df["pred_sentiment"])]
    lines += ["", "## Contoh salah sentimen (wajib ada di laporan)", ""]
    for r in bad_sent.head(10).itertuples():
        lines.append(f"- manual **{r.gold_sentiment}**, mesin **{r.pred_sentiment}**: {_snip(r.text_clean)}")
    if bad_sent.empty:
        lines.append("- tidak ada pada sampel ini")
    bad_link = df[df["gold_link"] == "n"].sort_values("link_confidence", ascending=False)
    lines += ["", "## Contoh tautan salah (kalimat bukan tentang pemain)", ""]
    for r in bad_link.head(10).itertuples():
        lines.append(f"- confidence {r.link_confidence:.2f}, flag `{r.link_flags or '-'}`: {_snip(r.text_clean)}")
    if bad_link.empty:
        lines.append("- tidak ada pada sampel ini")
    lines += ["", "Catatan: interval 95% pada sampel sekitar 100 kalimat lebar (±8–10 poin); "
              "laporkan angka beserta intervalnya, bukan angka tunggal."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------- team eval sheet
TEAM_OVERLAP = "ALL_4_OVERLAP"


def read_team_sheets(paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Read one or more filled copies of eval_linking_sentiment.csv.

    Each path is one annotator's copy (annotator = file stem); the sheet has no aspect
    labels. Returns (long labels, key, expected label count). The key marks the
    ALL_4_OVERLAP rows as shared, so kappa can be computed once several copies exist.
    """
    rows, key, problems = [], {}, Counter()
    for path in paths:
        for rec in _read_csv(path).to_dict("records"):
            item = f"E{int(rec['eval_idx']):03d}"
            slot = rec["annotator_slot"].strip()
            key.setdefault(item, {"item_id": item, "text_id": rec["text_id"], "player_id": rec["player_id"],
                                  "assigned": "ALL" if slot == TEAM_OVERLAP else slot})
            link, sentiment = parse_link(rec["manual_link_ok"]), parse_sentiment(rec["manual_sentiment"])
            filled = bool(rec["manual_link_ok"].strip())
            if filled and link is None:
                problems["manual_link_ok tidak dikenali"] += 1
            if link == "y" and not rec["manual_sentiment"].strip():
                problems["sentimen kosong pada baris y"] += 1
            if link == "y" and rec["manual_sentiment"].strip() and sentiment is None:
                problems["manual_sentiment tidak dikenali"] += 1
            rows.append({"annotator": path.stem, "item_id": item, "filled": filled, "link": link,
                         "sentiment": sentiment, "aspects": set()})
    long = pd.DataFrame(rows)
    long.attrs["problems"] = dict(problems)
    key_df = pd.DataFrame(key.values())
    shared = int((key_df["assigned"] == "ALL").sum())
    expected = shared * len(paths) + (len(key_df) - shared)
    return long, key_df, expected


# --------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual labelling and evaluation")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sheet = sub.add_parser("sheet", help="draw sentences and write one CSV per annotator")
    sheet.add_argument("--n", type=int, default=100)
    sheet.add_argument("--overlap", type=int, default=12)
    sheet.add_argument("--annotators", default="A,B,C,D")
    team = sub.add_parser("eval-team", help="evaluate the team's eval_linking_sentiment.csv (one or more filled copies)")
    team.add_argument("--sheets", nargs="+", type=Path,
                      default=[ROOT / "data" / "interim" / "eval_linking_sentiment.csv"])
    score = sub.add_parser("score", help="evaluate the filled sheets")
    score.add_argument("--annotators", default="A,B,C,D")
    for p in (sheet, score):
        p.add_argument("--labels-dir", default=str(LABELS_DIR))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    if args.cmd == "eval-team":
        long, key, expected = read_team_sheets(args.sheets)
        if not long["filled"].any():
            raise SystemExit("no labels filled in the given sheet(s): nothing to evaluate")
        linked = pd.read_parquet(PROCESSED / "texts_linked.parquet")
        analysis = pd.read_parquet(PROCESSED / "text_analysis.parquet")
        result = evaluate(build_gold(long), key, linked, analysis, long, expected, aspects_labelled=False)
        path = write_report(result, REPORT)
        log.info("link precision %.1f%% | sentiment accuracy %.1f%% | report -> %s",
                 100 * result["link"]["precision"], 100 * result["sentiment"]["accuracy"], path)
        return 0

    cfg = load_config()
    annotators = [a.strip() for a in args.annotators.split(",") if a.strip()]
    directory = Path(args.labels_dir)

    if args.cmd == "sheet":
        sentences = load_sentences(PROCESSED / "texts_linked.parquet", ROOT / cfg["text_sample"]["locked_file"])
        sheets, key = build_sheets(sentences, args.n, args.overlap, annotators,
                                   int(cfg["text_sample"]["random_seed"]))
        write_sheets(sheets, key, directory)
        for who, sh in sheets.items():
            log.info("label_%s.csv: %d sentences", who, len(sh))
        log.info("kolom yang diisi: %s. Jangan buka _key.csv sebelum selesai.", ", ".join(LABEL_COLUMNS))
        return 0

    key = pd.read_csv(directory / "_key.csv")
    linked = pd.read_parquet(PROCESSED / "texts_linked.parquet")
    analysis = pd.read_parquet(PROCESSED / "text_analysis.parquet")
    long = read_labels(directory, annotators, set(cfg["nlp"]["aspects"]))
    if long.empty:
        raise SystemExit(f"no label files in {directory}")
    expected = int(key["assigned"].map(lambda a: len(annotators) if a == "ALL" else 1).sum())
    result = evaluate(build_gold(long), key, linked, analysis, long, expected)
    path = write_report(result, REPORT)
    log.info("link precision %.1f%% | sentiment accuracy %.1f%% | report -> %s",
             100 * result["link"]["precision"], 100 * result["sentiment"]["accuracy"], path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())