"""Stage E figures (person D): scatter, aspect heatmap, candidate shortlist.

Reads  data/processed/player_summary.parquet and candidates.csv (from `src.score.rank`)
Writes reports/figures/scatter_quality_vs_value.png
       reports/figures/heatmap_aspects.png
       reports/candidate_shortlist.md  (+ reports/figures/candidate_shortlist.png)

What the figures do and do not claim (AGENTS.md "Keterbatasan"):
  * Players with evidence "tidak cukup" are drawn hollow and never labelled: their
    score is mostly the position prior, not their own comments.
  * A heatmap cell is blank when the player has fewer than `min_aspect_n` sentences
    on that aspect, instead of showing a mean of one or two sentences.
  * The shortlist keeps rows the ratings do not back ("di bawah median",
    "tidak ada rating") and says so; only "di atas median" rows are findings.

    python -m src.viz.report [--summary PATH] [--candidates PATH] [--out DIR]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import ROOT, load_config  # noqa: E402

log = logging.getLogger("viz.report")
PROCESSED = ROOT / "data" / "processed"
OUT_DIR = ROOT / "reports"
MIN_ASPECT_N = 3  # same default as rank.PARAMS["min_aspect_n"]
EVIDENCE_STYLE = {
    "cukup": {"color": "#1f77b4", "filled": True, "label": "cukup (>=30 teks)"},
    "terbatas": {"color": "#ff7f0e", "filled": True, "label": "terbatas (10-29)"},
    "tidak cukup": {"color": "#9e9e9e", "filled": False, "label": "tidak cukup (<10)"},
}


def scatter(summary: pd.DataFrame, path: Path) -> int:
    """Text quality score against market value; returns the number of players drawn."""
    df = summary[summary["text_quality_score"].notna() & summary["market_value_eur"].gt(0)]
    fig, ax = plt.subplots(figsize=(9, 6))
    for level, style in EVIDENCE_STYLE.items():
        part = df[df["evidence_level"] == level]
        if part.empty:
            continue
        x = part["market_value_eur"] / 1e6
        if part["score_ci_low"].notna().any():
            yerr = np.vstack(
                [
                    (part["text_quality_score"] - part["score_ci_low"]).clip(lower=0),
                    (part["score_ci_high"] - part["text_quality_score"]).clip(lower=0),
                ]
            )
            ax.errorbar(x, part["text_quality_score"], yerr=yerr, fmt="none",
                        ecolor=style["color"], alpha=0.25, lw=1)
        ax.scatter(
            x, part["text_quality_score"], s=45,
            facecolors=style["color"] if style["filled"] else "none",
            edgecolors=style["color"], label=f"{style['label']}  n={len(part)}",
        )
    cand = df[df["candidate_initial"].fillna(False).astype(bool)]
    ax.scatter(cand["market_value_eur"] / 1e6, cand["text_quality_score"], s=170,
               facecolors="none", edgecolors="crimson", lw=2, label="kandidat awal")
    for r in cand.itertuples():
        ax.annotate(r.name_canonical, (r.market_value_eur / 1e6, r.text_quality_score),
                    xytext=(6, 6), textcoords="offset points", fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("Nilai pasar (juta EUR, skala log)")
    ax.set_ylabel("Skor Kualitas Teks (-1..1, ditarik ke rata-rata posisi)")
    ax.set_title("Skor Kualitas Teks vs nilai pasar (batang = interval bootstrap 95%)")
    ax.axhline(0, color="black", lw=0.5)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return len(df)


def aspect_matrix(summary: pd.DataFrame, min_n: int = MIN_ASPECT_N) -> pd.DataFrame:
    """Players (evidence 'cukup') x aspects, NaN where fewer than `min_n` sentences."""
    names = sorted(c[4:] for c in summary.columns if c.startswith("asp_"))
    rows = summary[summary["evidence_level"] == "cukup"].sort_values(
        ["position_group", "name_canonical"]
    )
    mat = pd.DataFrame(index=rows["name_canonical"] + " (" + rows["position_group"] + ")")
    for name in names:
        values = rows[f"asp_{name}"].to_numpy(dtype=float)
        counts = rows.get(f"n_asp_{name}", pd.Series(0, index=rows.index)).fillna(0).to_numpy()
        mat[name] = np.where(counts >= min_n, values, np.nan)
    return mat.dropna(how="all")


def heatmap(summary: pd.DataFrame, path: Path, min_n: int = MIN_ASPECT_N) -> tuple[int, int]:
    mat = aspect_matrix(summary, min_n)
    if mat.empty:
        log.warning("heatmap: no player has >= %d sentences on any aspect", min_n)
        return 0, 0
    fig, ax = plt.subplots(figsize=(1.0 + 0.9 * mat.shape[1], 1.5 + 0.28 * mat.shape[0]))
    im = ax.imshow(np.ma.masked_invalid(mat.to_numpy()), cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(mat.shape[1]), mat.columns, rotation=45, ha="right")
    ax.set_yticks(range(mat.shape[0]), mat.index, fontsize=7)
    fig.colorbar(im, ax=ax, label="rata-rata sentimen aspek")
    ax.set_title(f"Sentimen per aspek (sel kosong: kurang dari {min_n} kalimat)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return mat.shape


def shortlist(candidates: pd.DataFrame, md_path: Path, png_path: Path) -> int:
    """Markdown table of the shortlist plus a PNG copy; returns the row count."""
    table = candidates.copy()
    if "market_value_eur" in table:
        table["nilai (juta EUR)"] = (table.pop("market_value_eur") / 1e6).round(1)
    for col in ("text_quality_score", "score_ci_low", "score_ci_high", "rating_pos_zscore"):
        if col in table:
            table[col] = table[col].round(2)
    if {"score_ci_low", "score_ci_high"} <= set(table.columns):
        table["CI 95%"] = "[" + table.pop("score_ci_low").astype(str) + ", " + table.pop("score_ci_high").astype(str) + "]"
    table = table.fillna("-")

    backed = int((candidates.get("validasi_rating", pd.Series(dtype=str)) == "di atas median").sum())
    lines = [
        "# Daftar kandidat awal (teks + harga)",
        "",
        f"{len(table)} kandidat. Hanya yang berstatus **di atas median** yang didukung rating: **{backed}**. "
        "Baris lain tetap ditampilkan karena kandidat yang tidak didukung angka juga hasil.",
        "",
    ]
    if table.empty:
        lines.append("_Tidak ada pemain yang lolos ambang teks dan harga._")
    else:
        cols = list(table.columns)
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in table.itertuples(index=False)]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not table.empty:
        fig, ax = plt.subplots(figsize=(1.6 * len(table.columns) * 0.6 + 4, 0.5 + 0.4 * len(table)))
        ax.axis("off")
        tab = ax.table(cellText=table.astype(str).to_numpy(), colLabels=list(table.columns), loc="center")
        tab.auto_set_font_size(False)
        tab.set_fontsize(7)
        tab.auto_set_column_width(range(len(table.columns)))
        fig.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    return len(table)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage E: figures and shortlist")
    parser.add_argument("--summary", default=str(PROCESSED / "player_summary.parquet"))
    parser.add_argument("--candidates", default=str(PROCESSED / "candidates.csv"))
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    for p in (args.summary, args.candidates):
        if not Path(p).exists():
            raise SystemExit(f"{p} not found - run `python -m src.score.rank` first")
    summary = pd.read_parquet(args.summary)
    candidates = pd.read_csv(args.candidates)
    out = Path(args.out)
    fig_dir = out / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    min_n = int(load_config().get("scoring", {}).get("min_aspect_n", MIN_ASPECT_N))

    n = scatter(summary, fig_dir / "scatter_quality_vs_value.png")
    log.info("scatter: %d players -> %s", n, fig_dir / "scatter_quality_vs_value.png")
    rows, cols = heatmap(summary, fig_dir / "heatmap_aspects.png", min_n)
    log.info("heatmap: %d players x %d aspects -> %s", rows, cols, fig_dir / "heatmap_aspects.png")
    m = shortlist(candidates, out / "candidate_shortlist.md", fig_dir / "candidate_shortlist.png")
    log.info("candidate shortlist: %d rows -> %s", m, out / "candidate_shortlist.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())