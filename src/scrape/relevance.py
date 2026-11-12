"""Retrieval relevance harness (PRD §11, target >= 85% on 100 labelled texts).

Day 2 gate: 100 drawn texts are read by hand and marked relevant or not. This
module draws the sheet and turns the filled sheet into a report with numbers, so
the claim "85% relevance" traces back to a file in the repo.

Selection is a uniform random sample seeded by `text_sample.random_seed` from
config (AGENTS.md rule 13), so 100 texts really are random and the draw is
reproducible by any teammate on the same file.

**Sources.** `source="reddit"` is the default and behaves exactly as before: same
sheet name, same report name, same numbers. YouTube has its own sheet and report
so one gate can never overwrite the other, and `source="all"` measures the union
without disturbing either per-source figure.
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

SOURCES = ("reddit", "youtube", "all")
SOURCE_LABELS = {"reddit": "Reddit", "youtube": "YouTube", "all": "Reddit + YouTube"}


def review_csv(source: str = "reddit") -> Path:
    """Sheet path. Reddit keeps the original filename, so nothing existing moves."""
    if source == "reddit":
        return REVIEW_CSV
    return INTERIM / f"review_relevance_{source}.csv"


def report_path(source: str = "reddit") -> Path:
    if source == "reddit":
        return REPORT
    return ROOT / "reports" / f"retrieval_relevance_{source}.md"


def _latest_files(source: str, tag: str | None) -> list[Path]:
    pattern = f"texts_{source}_{tag}.jsonl" if tag else f"texts_{source}_*.jsonl"
    candidates = sorted(INTERIM.glob(pattern), key=lambda p: p.stat().st_mtime)
    return candidates[-1:] if candidates else []


def _texts(tag: str | None = None, source: str = "reddit") -> list[dict]:
    """Read the newest scraped texts for `source`.

    `all` reads the newest file from each source, so the union can be measured
    without changing either per-source number.
    """
    if source == "all":
        files: list[Path] = []
        for one in ("reddit", "youtube"):
            files.extend(_latest_files(one, tag))
    else:
        files = _latest_files(source, tag)

    if not files:
        raise SystemExit(
            f"no scraped texts for source={source!r} in {INTERIM}. Run "
            "`make scrape` / `make scrape-pilot` (Reddit) or "
            "`python -m src.scrape.youtube` (YouTube) first."
        )

    rows: list[dict] = []
    for path in files:
        log.info("reading %s", path.name)
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return [r for r in rows if r.get("unit_type") == "comment"]


def sample_for_review(n: int = 100, tag: str | None = None, source: str = "reddit") -> Path:
    """Draw `n` texts with `random.sample` and the seed from config.

    AGENTS.md and PRD §11 ask for 100 *random* texts. The earlier hash +
    round-robin draw was deterministic but not random - it over-sampled players
    with few texts - so the gate number would not be the number the rule
    describes. The seed lives in `text_sample.random_seed` (rule 13), so the draw
    is reproducible by anyone on the same file.
    """
    if source not in SOURCES:
        raise SystemExit(f"unknown source {source!r}; expected one of {SOURCES}")

    # The Reddit path keeps its original call shape on purpose: stubs and callers
    # that replace `_texts` with a one-argument function must keep working, so
    # adding YouTube cannot break the existing gate.
    rows = _texts(tag) if source == "reddit" else _texts(tag, source)
    if not rows:
        raise SystemExit("no comment-level texts to sample")

    sheet = review_csv(source)
    # YouTube records carry `channel`; Reddit's header stays untouched.
    fields = FIELDS + (["channel"] if source != "reddit" else [])

    # Never destroy annotation work: a sheet with any label is not regenerated.
    if sheet.exists():
        with sheet.open(encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
        if any(_parse_label(r.get("relevant", "")) is not None for r in existing):
            raise SystemExit(
                f"{sheet} already has labels. Move or delete it before drawing a "
                "new sheet, so a filled gate is not silently emptied."
            )

    seed = int(load_config()["text_sample"]["random_seed"])
    picked = random.Random(seed).sample(rows, min(n, len(rows)))

    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in picked:
            writer.writerow({**{k: row.get(k, "") for k in fields}, "relevant": ""})
    log.info("wrote %d texts for review -> %s", len(picked), sheet)
    return sheet


def _parse_label(value: str) -> bool | None:
    raw = (value or "").strip().lower()
    if raw in {"y", "yes", "1", "true", "relevan", "relevant"}:
        return True
    if raw in {"n", "no", "0", "false", "tidak", "not relevant"}:
        return False
    return None


def score_review(
    path: Path | None = None,
    target: float = 0.85,
    min_labelled: int = 100,
    source: str = "reddit",
) -> tuple[Path, dict]:
    """Turn the filled sheet into the gate report.

    `LULUS` requires a rate >= target, at least `min_labelled` labels, *and* no
    blank rows left in the sheet. A rate over a partly blank sheet is not the
    measurement the gate describes: the blanks are texts nobody read, and reading
    only the easy ones inflates the number.
    """
    sheet = Path(path) if path else review_csv(source)
    report = report_path(source)
    group_field = "channel" if source == "youtube" else "subreddit"
    group_title = "channel" if source == "youtube" else "subreddit"

    if not sheet.exists():
        raise SystemExit(f"review sheet not found: {sheet} - run `make review` first")
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    labelled = [(r, _parse_label(r.get("relevant", ""))) for r in rows]
    done = [(r, ok) for r, ok in labelled if ok is not None]
    skipped = len(labelled) - len(done)
    if not done:
        raise SystemExit(
            f"{sheet} has no labels yet. Fill the 'relevant' column with y/n, then rerun."
        )

    relevant = sum(1 for _, ok in done if ok)
    rate = relevant / len(done)
    enough = len(done) >= min_labelled
    passed = enough and skipped == 0 and rate >= target

    by_group: dict[str, list[bool]] = defaultdict(list)
    for row, ok in done:
        key = row.get(group_field) or row.get("subreddit") or "?"
        by_group[key].append(bool(ok))

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
        f"# Relevansi Retrieval {SOURCE_LABELS.get(source, source)} (Tahap B)",
        "",
        f"- Teks dilabeli: **{len(done)}** dari {len(rows)} ditarik ({skipped} kosong)",
        f"- Relevan: **{relevant}**",
        f"- Relevansi: **{rate:.1%}** (target PRD §11: >= {target:.0%})",
        f"- Status: **{status}**",
        "",
        "Cara sampel diambil: `random.sample` dengan seed `text_sample.random_seed` dari "
        "`config/config.yaml` — sampel acak seragam atas semua komentar di file "
        f"`texts_{source}_*.jsonl` yang dipakai. Seednya sama untuk semua anggota tim, jadi "
        "lembar yang sama bisa dibuat ulang. `LULUS` hanya diberikan bila minimal "
        f"{min_labelled} teks dilabeli.",
        "",
        f"## Per {group_title}",
        "",
        f"| {group_title.capitalize()} | Dilabeli | Relevan | Relevansi |",
        "|---|---|---|---|",
    ]
    for group, oks in sorted(by_group.items(), key=lambda kv: -len(kv[1])):
        label = f"r/{group}" if source != "youtube" else group
        lines.append(f"| {label} | {len(oks)} | {sum(oks)} | {sum(oks) / len(oks):.0%} |")

    lines += ["", "## Contoh teks tidak relevan (wajib ada di laporan)", ""]
    for row in failures[:10]:
        snippet = " ".join(row["text_clean"].split())[:220]
        where = row.get(group_field) or row.get("subreddit") or "?"
        label = f"r/{where}" if source != "youtube" else where
        lines.append(f"- `{row['player_id']}` {label}: {snippet}")
    if not failures:
        lines.append("- tidak ada pada sampel ini")

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stats = {
        "labelled": len(done),
        "relevant": relevant,
        "rate": rate,
        "failures": len(failures),
        "passed": passed,
    }
    log.info("relevance %.1f%% on %d labelled texts -> %s", rate * 100, len(done), report)
    return report, stats
