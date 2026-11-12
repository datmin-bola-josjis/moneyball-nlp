"""Retrieval relevance harness (PRD §11, target >= 85% on 100 labelled texts).

Day 2 gate: 100 drawn texts are read by hand and marked relevant or not. This
module draws the sheet and turns the filled sheet into a report with numbers, so
the claim "85% relevance" traces back to a file in the repo.

Selection is a uniform random sample seeded by `text_sample.random_seed` from
config (AGENTS.md rule 13), so 100 texts really are random and the draw is
reproducible by any teammate on the same file.
"""

from __future__ import annotations

import csv
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

from src.config import ROOT, load_config

log = logging.getLogger("relevance")
INTERIM = ROOT / "data" / "interim"
REVIEW_CSV = INTERIM / "review_relevance.csv"
REPORT = ROOT / "reports" / "retrieval_relevance.md"
FIELDS = ["text_id", "player_id", "subreddit", "created_at", "url", "text_clean", "relevant"]


def _texts(tag: str | None = None) -> list[dict]:
    """Read the newest `texts_reddit_<tag>.jsonl`, so pilot and full runs both work."""
    pattern = f"texts_reddit_{tag}.jsonl" if tag else "texts_reddit_*.jsonl"
    candidates = sorted(INTERIM.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(
            f"no scraped texts matching {INTERIM / pattern} - run `make scrape` "
            "or `make scrape-pilot` first"
        )
    path = candidates[-1]
    log.info("reading %s", path.name)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("unit_type") == "comment"]


def sample_for_review(n: int = 100, tag: str | None = None) -> Path:
    """Draw `n` texts with `random.sample` and the seed from config.

    AGENTS.md and PRD §11 ask for 100 *random* texts. The earlier hash +
    round-robin draw was deterministic but not random - it over-sampled players
    with few texts - so the gate number would not be the number the rule
    describes. The seed lives in `text_sample.random_seed` (rule 13), so the draw
    is reproducible by anyone on the same file.
    """
    rows = _texts(tag)
    if not rows:
        raise SystemExit("no comment-level texts to sample")

    # Never destroy annotation work: a sheet with any label is not regenerated.
    if REVIEW_CSV.exists():
        with REVIEW_CSV.open(encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
        if any(_parse_label(r.get("relevant", "")) is not None for r in existing):
            raise SystemExit(
                f"{REVIEW_CSV} already has labels. Move or delete it before drawing a "
                "new sheet, so a filled gate is not silently emptied."
            )

    seed = int(load_config()["text_sample"]["random_seed"])
    picked = random.Random(seed).sample(rows, min(n, len(rows)))

    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in picked:
            writer.writerow({**{k: row.get(k, "") for k in FIELDS}, "relevant": ""})
    log.info("wrote %d texts for review -> %s", len(picked), REVIEW_CSV)
    return REVIEW_CSV


def _parse_label(value: str) -> bool | None:
    raw = (value or "").strip().lower()
    if raw in {"y", "yes", "1", "true", "relevan", "relevant"}:
        return True
    if raw in {"n", "no", "0", "false", "tidak", "not relevant"}:
        return False
    return None


def score_review(
    path: Path = REVIEW_CSV, target: float = 0.85, min_labelled: int = 100
) -> tuple[Path, dict]:
    """Turn the filled sheet into the gate report.

    `LULUS` requires a rate >= target, at least `min_labelled` labels, *and* no
    blank rows left in the sheet. A rate over a partly blank sheet is not the
    measurement the gate describes: the blanks are texts nobody read, and reading
    only the easy ones inflates the number.
    """
    if not path.exists():
        raise SystemExit(f"review sheet not found: {path} - run `make review` first")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    labelled = [(r, _parse_label(r.get("relevant", ""))) for r in rows]
    done = [(r, ok) for r, ok in labelled if ok is not None]
    skipped = len(labelled) - len(done)
    if not done:
        raise SystemExit(
            f"{path} has no labels yet. Fill the 'relevant' column with y/n, then rerun."
        )

    relevant = sum(1 for _, ok in done if ok)
    rate = relevant / len(done)
    enough = len(done) >= min_labelled
    passed = enough and skipped == 0 and rate >= target

    by_sub: dict[str, list[bool]] = defaultdict(list)
    for row, ok in done:
        by_sub[row.get("subreddit", "?")].append(bool(ok))

    failures = [row for row, ok in done if not ok]
    if not enough:
        status = f"BELUM LULUS — baru {len(done)}/{min_labelled} teks dilabeli"
    elif skipped:
        status = f"BELUM LULUS — {skipped} teks belum dilabeli"
    elif passed:
        status = "LULUS"
    else:
        status = "BELUM LULUS"
    lines = [
        "# Relevansi Retrieval Reddit (Tahap B)",
        "",
        f"- Teks dilabeli: **{len(done)}** dari {len(rows)} ditarik ({skipped} kosong)",
        f"- Relevan: **{relevant}**",
        f"- Relevansi: **{rate:.1%}** (target PRD §11: >= {target:.0%})",
        f"- Status: **{status}**",
        "",
        "Cara sampel diambil: `random.sample` dengan seed `text_sample.random_seed` dari "
        "`config/config.yaml` — sampel acak seragam atas semua komentar di file "
        "`texts_reddit_*.jsonl` yang dipakai. Seednya sama untuk semua anggota tim, jadi "
        "lembar yang sama bisa dibuat ulang. `LULUS` hanya diberikan bila minimal "
        f"{min_labelled} teks dilabeli.",
        "",
        "## Per subreddit",
        "",
        "| Subreddit | Dilabeli | Relevan | Relevansi |",
        "|---|---|---|---|",
    ]
    for sub, oks in sorted(by_sub.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| r/{sub} | {len(oks)} | {sum(oks)} | {sum(oks) / len(oks):.0%} |")

    lines += ["", "## Contoh teks tidak relevan (wajib ada di laporan)", ""]
    for row in failures[:10]:
        snippet = " ".join(row["text_clean"].split())[:220]
        lines.append(f"- `{row['player_id']}` r/{row.get('subreddit', '?')}: {snippet}")
    if not failures:
        lines.append("- tidak ada pada sampel ini")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stats = {
        "labelled": len(done),
        "relevant": relevant,
        "rate": rate,
        "failures": len(failures),
        "passed": passed,
    }
    log.info("relevance %.1f%% on %d labelled texts -> %s", rate * 100, len(done), REPORT)
    return REPORT, stats
