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
import hashlib
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
# `player_name`/`club` are not decoration: a labeller cannot answer "is this text
# about this player?" from an opaque `fotmob_123` id, and opening 100 URLs by hand
# to find out is why the gate stalled. They are read-only context, never scored.
FIELDS = [
    "text_id",
    "player_id",
    "player_name",
    "club",
    "subreddit",
    "created_at",
    "url",
    "text_clean",
    "relevant",
]

SOURCES = ("reddit", "youtube", "all")
SOURCE_LABELS = {"reddit": "Reddit", "youtube": "YouTube", "all": "Reddit + YouTube"}

# Both halves of the Indonesian pair are accepted. Accepting only `tidak` was an
# asymmetry, not a decision: an annotator writing `ya` was silently treated as
# blank, so a sheet that looked finished scored BELUM LULUS on a mystery gap.
# `labels.py` mirrors these sets and `tests/test_labels.py` pins the equivalence.
TRUE_LABELS = frozenset({"y", "yes", "1", "true", "relevan", "relevant", "ya"})
FALSE_LABELS = frozenset({"n", "no", "0", "false", "tidak", "not relevant"})
# Answering "undecided" is still an answer: it must never count toward the rate,
# and it must never be confused with a row nobody opened.
UNCERTAIN_LABELS = frozenset({"ragu", "ragu-ragu", "unsure", "unclear"})


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


def _with_player_identity(
    rows: list[dict], source: str, tag: str | None = None
) -> list[dict]:
    """Attach `player_name` and `club` so the sheet can be judged without the repo.

    The join is on `player_id`, never on a name (AGENTS.md rule 4). Identity comes
    from the locked sample rather than from the scraped payload, because the
    payload is text-only and a name typed into a sheet by hand would be a second
    source of truth.

    When the sample file is absent (a checkout that has only scraped texts) the
    columns are left blank rather than guessed: a wrong name next to unfamiliar
    prose is worse than no name, because it primes the labeller.
    """
    names: dict[str, tuple[str, str]] = {}
    sample = ROOT / "data" / "processed" / "text_sample.parquet"
    if sample.exists():
        try:
            import pandas as pd

            frame = pd.read_parquet(sample, columns=["player_id", "name_canonical", "club"])
            names = {
                str(row.player_id): (str(row.name_canonical or ""), str(row.club or ""))
                for row in frame.itertuples(index=False)
            }
        except Exception as exc:  # a broken sample must not block the gate
            log.warning("could not read player identity from %s: %s", sample.name, exc)

    out: list[dict] = []
    for row in rows:
        name, club = names.get(str(row.get("player_id") or ""), ("", ""))
        out.append({**row, "player_name": name, "club": club})
    return out


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
    # `ragu` counts as work. Testing only `_parse_label` treated a sheet full of
    # undecided rows as untouched and overwrote it.
    if sheet.exists():
        with sheet.open(encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
        if any(_has_label(r) for r in existing):
            raise SystemExit(
                f"{sheet} already has labels. Move or delete it before drawing a "
                "new sheet, so a filled gate is not silently emptied."
            )

    seed = int(load_config()["text_sample"]["random_seed"])
    picked = random.Random(seed).sample(rows, min(n, len(rows)))
    picked = _with_player_identity(picked, source, tag)

    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in picked:
            writer.writerow({**{k: row.get(k, "") for k in fields}, "relevant": ""})
    log.info("wrote %d texts for review -> %s", len(picked), sheet)
    return sheet


def _parse_label(value: str) -> bool | None:
    """True/False for a decision, None for anything that is not one.

    `ragu` is None on purpose: an undecided row is not evidence either way, so it
    must never reach the rate. `_is_uncertain` tells it apart from a blank, which
    matters because the two mean opposite things about the annotator's work.
    """
    raw = (value or "").strip().lower()
    if raw in TRUE_LABELS:
        return True
    if raw in FALSE_LABELS:
        return False
    return None


def _is_uncertain(value: str) -> bool:
    """True when the annotator answered, but could not decide either way."""
    return (value or "").strip().lower() in UNCERTAIN_LABELS


def _has_label(row: dict) -> bool:
    """True when a cell holds any human answer, decided or not.

    Used by the redraw guard. Checking `_parse_label` alone treated a sheet full
    of `ragu` as untouched and regenerated it, which would have destroyed the
    annotator's work - the exact outcome the guard exists to prevent.
    """
    value = row.get("relevant", "")
    return _parse_label(value) is not None or _is_uncertain(value)


def sheet_fingerprint(rows: list[dict]) -> str:
    """Stable id for the exact rows a report was scored from.

    A report is only true for the sheet it was scored from. When the sheet is
    redrawn, the old numbers stay on disk looking authoritative - which is what
    happened once already: `retrieval_relevance.md` claimed LULUS 94% from a
    sheet that had since been replaced, and nothing in the file revealed it.

    The hash covers each row's id *and* its text, sorted by id. Hashing ids alone
    would miss the case that matters most for a labelling sheet: the same id
    pointing at different prose, which is exactly what a re-scrape produces when
    a comment is edited or an id scheme is reused.
    """
    payload = "\n".join(
        f"{row.get('text_id') or ''}\x00{row.get('text_clean') or ''}"
        for row in sorted(rows, key=lambda r: str(r.get("text_id") or ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


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

    Blank and `ragu` both block the pass, but they are reported separately. A
    blank means nobody opened the row; `ragu` means a human read it and could not
    decide, which is a finding about the sample, not a missing shift. Collapsing
    the two hid the second one inside a "belum dilabeli" that was not true.
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
    # Counted from the raw cell, so a decided row is never also counted as uncertain.
    uncertain = sum(1 for r, ok in labelled if ok is None and _is_uncertain(r.get("relevant", "")))
    skipped = len(labelled) - len(done) - uncertain
    if not done:
        if uncertain:
            raise SystemExit(
                f"{sheet} has no decided labels yet: {uncertain} row(s) say 'ragu'. "
                "A row marked unsure is not evidence either way, so nothing can be "
                "scored until those rows are settled. To start over instead, move or "
                "delete the sheet and run `make review`; the redraw guard will not "
                "overwrite a sheet that holds answers, not even undecided ones."
            )
        raise SystemExit(
            f"{sheet} has no labels yet. Fill the 'relevant' column with y/n "
            "('ya'/'tidak' are accepted too), then rerun."
        )

    relevant = sum(1 for _, ok in done if ok)
    rate = relevant / len(done)
    enough = len(done) >= min_labelled
    passed = enough and skipped == 0 and uncertain == 0 and rate >= target

    by_group: dict[str, list[bool]] = defaultdict(list)
    for row, ok in done:
        key = row.get(group_field) or row.get("subreddit") or "?"
        by_group[key].append(bool(ok))

    failures = [row for row, ok in done if not ok]
    # The quorum branch names the shortfall, so it must also say how much of that
    # shortfall is already read-but-undecided rather than untouched. Without the
    # suffix, 95 labels + 5 `ragu` and 95 labels + 5 blanks printed the same
    # line, and the annotator was told to do work they had already done.
    if not enough:
        shortfall = []
        if uncertain:
            shortfall.append(f"{uncertain} sudah ditandai 'ragu'")
        if skipped:
            shortfall.append(f"{skipped} masih kosong")
        tail = f" ({', '.join(shortfall)})" if shortfall else ""
        status = f"BELUM LULUS — baru {len(done)}/{min_labelled} teks dilabeli{tail}"
    elif skipped:
        status = f"BELUM LULUS — {skipped} teks belum dilabeli" + (
            f", {uncertain} ditandai 'ragu'" if uncertain else ""
        )
    elif uncertain:
        status = f"BELUM LULUS — {uncertain} teks ditandai 'ragu' dan tidak dihitung"
    elif passed:
        status = "LULUS"
    else:
        status = "BELUM LULUS"
    fingerprint = sheet_fingerprint(rows)
    # "0 kosong, 2 ragu" rather than a nested "(0 kosong (2 ragu))": the two counts
    # are read together and a nested parenthetical hid the second one.
    blanks = f"{skipped} kosong" + (f", {uncertain} ragu" if uncertain else "")
    lines = [
        f"# Relevansi Retrieval {SOURCE_LABELS.get(source, source)} (Tahap B)",
        "",
        f"- Teks dilabeli: **{len(done)}** dari {len(rows)} ditarik ({blanks})",
        f"- Relevan: **{relevant}**",
        f"- Relevansi: **{rate:.1%}** (target PRD §11: >= {target:.0%})",
        f"- Status: **{status}**",
        f"- Sidik jari sampel: `{fingerprint}` (dari `{sheet.name}`)",
        "",
        "Cara sampel diambil: `random.sample` dengan seed `text_sample.random_seed` dari "
        "`config/config.yaml` — sampel acak seragam atas semua komentar di file "
        f"`texts_{source}_*.jsonl` yang dipakai. Seednya sama untuk semua anggota tim, jadi "
        "lembar yang sama bisa dibuat ulang. `LULUS` hanya diberikan bila minimal "
        f"{min_labelled} teks dilabeli. Sidik jari di atas berubah bila lembar ditarik "
        "ulang, jadi angka di laporan ini hanya berlaku untuk lembar dengan sidik jari itu.",
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
        "fingerprint": fingerprint,
        "uncertain": uncertain,
        "skipped": skipped,
    }
    log.info("relevance %.1f%% on %d labelled texts -> %s", rate * 100, len(done), report)
    return report, stats
