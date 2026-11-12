"""Retrieval relevance harness (PRD §11, target >= 85% on 100 labelled texts).

Day 2 gate: 100 drawn texts are read by hand and marked relevant or not. This
module draws the sheet and turns the filled sheet into a report with numbers, so
the claim "85% relevance" traces back to a file in the repo.

Selection is deterministic - hash order within a player, round-robin across
players - instead of `random`: no seed to forget, and every teammate gets the
same sheet on the same data. It is not a uniform random sample, which is why the
report states the exact draw rule.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path

from src.config import ROOT

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


def _rank_key(row: dict) -> str:
    return hashlib.sha256(row["text_id"].encode()).hexdigest()


def sample_for_review(n: int = 100, tag: str | None = None) -> Path:
    rows = _texts(tag)
    if not rows:
        raise SystemExit("no comment-level texts to sample")

    by_player: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=_rank_key):
        by_player[row["player_id"]].append(row)

    # Round-robin so a player with 60 texts cannot fill the whole sheet.
    order = sorted(by_player, key=lambda pid: _rank_key({"text_id": pid}))
    picked: list[dict] = []
    take = min(n, len(rows))
    round_index = 0
    while len(picked) < take:
        for pid in order:
            bucket = by_player[pid]
            if round_index < len(bucket) and len(picked) < take:
                picked.append(bucket[round_index])
        round_index += 1

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


def score_review(path: Path = REVIEW_CSV, target: float = 0.85) -> tuple[Path, dict]:
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

    by_sub: dict[str, list[bool]] = defaultdict(list)
    for row, ok in done:
        by_sub[row.get("subreddit", "?")].append(bool(ok))

    failures = [row for row, ok in done if not ok]
    lines = [
        "# Relevansi Retrieval Reddit (Tahap B)",
        "",
        f"- Teks dilabeli: **{len(done)}** dari {len(rows)} ditarik ({skipped} kosong)",
        f"- Relevan: **{relevant}**",
        f"- Relevansi: **{rate:.1%}** (target PRD §11: >= {target:.0%})",
        f"- Status: **{'LULUS' if rate >= target else 'BELUM LULUS'}**",
        "",
        "Cara sampel diambil: urut hash `text_id` di dalam tiap pemain, lalu round-robin "
        "antar pemain, supaya satu pemain populer tidak mengisi seluruh lembar. Bukan "
        "sampel acak seragam; angka ini berlaku untuk aturan pengambilan tersebut.",
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
    stats = {"labelled": len(done), "relevant": relevant, "rate": rate, "failures": len(failures)}
    log.info("relevance %.1f%% on %d labelled texts -> %s", rate * 100, len(done), REPORT)
    return REPORT, stats
