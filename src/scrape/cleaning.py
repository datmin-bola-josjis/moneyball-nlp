"""Cleaning table for the YouTube path (PLAN §5 deliverable).

Every number in the table is a counter incremented inside
`src/scrape/youtube.py::records_from_comment`, so the table cannot drift from the
code that does the filtering. Reading a finished run's `summary.json` also means
the table can be regenerated without spending a single quota unit.

The unit being counted is a **(player, comment) pair**, not a unique comment: the
same top-level comment is examined once per player whose name it might mention.
That is the right denominator for "why did this text not become evidence for
this player", but it is not the number of comments in the corpus.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.config import ROOT

log = logging.getLogger("cleaning")

RAW = ROOT / "data" / "raw" / "youtube"
REPORT = ROOT / "reports" / "cleaning_youtube.md"

# The order the filters run in `records_from_comment`. A table sorted any other
# way would invite the reader to add the rows up in the wrong order.
COMMENT_FILTERS = [
    ("too_short", "Terlalu pendek", "kurang dari `min_words` kata (config)"),
    ("not_english", "Bukan bahasa Inggris", "deteksi bahasa"),
    ("bot_like", "Bot / spam", "penanda bot"),
    ("no_date", "Tanpa tanggal", "`publishedAt` kosong atau tidak valid"),
    ("outside_season", "Di luar musim", "di luar `league.season_start`..`season_end`"),
    ("duplicate", "Duplikat dalam satu pemain", "`text_clean_hash` sudah dipakai"),
    ("name_not_resolved", "Nama tidak teratasi", "aturan 17 / `AliasIndex`"),
]
SENTENCE_FILTERS = [
    ("sentence_not_resolved", "Nama tidak teratasi", "aturan 17 / `AliasIndex`"),
]


def latest_summary(base: Path | None = None) -> Path:
    folder = Path(base) if base is not None else RAW
    candidates = sorted(
        folder.glob("*/summary.json"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise SystemExit(
            f"no youtube run summary under {folder}. Run `make scrape-youtube` first."
        )
    return candidates[-1]


def load_summary(path: Path | None = None) -> tuple[dict, Path]:
    target = Path(path) if path is not None else latest_summary()
    if target.is_dir():
        target = target / "summary.json"
    if not target.exists():
        raise SystemExit(f"summary not found: {target}")
    summary = json.loads(target.read_text(encoding="utf-8"))
    if "filters" not in summary:
        raise SystemExit(
            f"{target} predates the per-filter counters. Rerun `make scrape-youtube` "
            "(cached, so it costs no quota) to produce them."
        )
    return summary, target


def _share(value: int, total: int) -> str:
    return f"{value / total:.1%}" if total else "—"


def render(summary: dict, run_name: str) -> str:
    filters = summary["filters"]
    dropped = filters.get("dropped", {})
    examined = int(filters.get("comments_examined", 0))
    kept = int(filters.get("comments_kept", 0))
    sentences = int(filters.get("sentences_kept", 0))

    lines = [
        "# Tabel Cleaning YouTube (Tahap B)",
        "",
        f"Run: `{run_name}`. Angka diambil dari `summary.json` run itu, dihitung oleh",
        "`src/scrape/cleaning.py` dari penghitung yang ada di",
        "`src/scrape/youtube.py::records_from_comment` — bukan ditulis manual.",
        "",
        "## Komentar",
        "",
        "| Filter | Dibuang | Porsi dari diperiksa | Alasan |",
        "|---|---|---|---|",
    ]
    for key, label, reason in COMMENT_FILTERS:
        value = int(dropped.get(key, 0))
        lines.append(f"| {label} | {value} | {_share(value, examined)} | {reason} |")

    lines += [
        f"| **Diperiksa** | **{examined}** | 100% | pasangan (pemain, komentar) |",
        f"| **Lolos menjadi komentar** | **{kept}** | {_share(kept, examined)} | |",
        "",
        f"Kalimat yang lolos: **{sentences}**.",
        "",
        "## Kalimat",
        "",
        "Kalimat disaring terpisah, setelah komentarnya lolos. Kalimat yang gugur",
        "tidak membatalkan komentarnya.",
        "",
        "| Filter | Dibuang | Alasan |",
        "|---|---|---|",
    ]
    for key, label, reason in SENTENCE_FILTERS:
        lines.append(f"| {label} | {int(dropped.get(key, 0))} | {reason} |")

    unaccounted = examined - kept - sum(int(dropped.get(k, 0)) for k, _, _ in COMMENT_FILTERS)
    lines += [
        "",
        "## Catatan cara membaca",
        "",
        "- Satuannya **pasangan (pemain, komentar)**, bukan komentar unik. Komentar",
        "  yang sama diperiksa sekali untuk setiap pemain yang namanya mungkin",
        "  disebut. Jadi angka \"diperiksa\" lebih besar dari jumlah komentar di",
        "  korpus, dan itu memang yang ingin dijelaskan: kenapa teks ini tidak",
        "  menjadi bukti untuk pemain ini.",
        f"- Baris diperiksa = lolos + semua filter. Selisih yang tidak terhitung: "
        f"**{unaccounted}** (komentar yang bikin `kept_comments` mencapai kuota di "
        "tengah halaman, jadi tidak sempat diperiksa).",
        "- Angka ini **tidak berubah** setelah teks Reddit dari B masuk: tabel ini",
        "  hanya menjelaskan jalur YouTube.",
        "",
        "## Perintah",
        "",
        "```bash",
        "make cleaning                       # dari run terbaru",
        "make cleaning RUN=<nama-folder-run>  # dari run tertentu",
        "```",
    ]
    return "\n".join(lines) + "\n"


def run(summary_path: Path | None = None, out: Path | None = None) -> Path:
    summary, path = load_summary(summary_path)
    target = Path(out) if out is not None else REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(summary, path.parent.name), encoding="utf-8")
    log.info("cleaning table -> %s", target)
    return target


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Stage B: render the YouTube cleaning table from a run summary"
    )
    parser.add_argument("--run", help="run folder name under data/raw/youtube")
    parser.add_argument("--out", help=f"output (default {REPORT.name})")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    summary_path = RAW / args.run if args.run else None
    run(summary_path, Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
