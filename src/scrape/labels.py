"""Progress and format checks for the three manual labelling sheets.

The human relevance gate (PRD §11, AGENTS.md rule 9) needs 300 hand labels
before any text-based finding stops being *indicative*. Nothing here fills a
label: the labels are a human judgement on English prose, and a model-written
label would not be evidence. What was missing is a way to see, without opening
three spreadsheets by eye, which rows are still blank and which cells hold a
value the scorer will silently ignore.

Two vocabularies are in play, and they are not identical. That is a real trap:

  * ``src/scrape/relevance._parse_label`` accepts ``relevan``/``relevant`` and
    ``tidak``/``not relevant`` in the relevance sheets.
  * ``src/nlp/analyze.score_eval_sheet`` accepts only
    ``y/yes/1/true/n/no/0/false`` for ``manual_link_ok``, so an annotator who
    writes ``relevan`` in the eval sheet is scored as *unlabelled*, not as a
    wrong answer.

Rather than guess which one the annotator meant, this module reports the value
as unusable and names the reason. A quiet reinterpretation would change a gate
number nobody could trace back.

Exit code is 1 when any sheet holds a value that cannot be used, so the command
can stand in a gate; it is 0 when the sheets are clean, including when they are
still completely empty.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.config import ROOT

log = logging.getLogger("labels.status")

REVIEW_REDDIT = ROOT / "data" / "interim" / "review_relevance.csv"
REVIEW_YOUTUBE = ROOT / "data" / "interim" / "review_relevance_youtube.csv"
EVAL_SHEET = ROOT / "data" / "interim" / "eval_linking_sentiment.csv"

# Mirrors `relevance._parse_label`; `tests/test_labels.py` pins the equivalence
# so the two cannot drift apart unnoticed.
RELEVANCE_TRUE = frozenset({"y", "yes", "1", "true", "relevan", "relevant"})
RELEVANCE_FALSE = frozenset({"n", "no", "0", "false", "tidak", "not relevant"})

# The narrower set `analyze.score_eval_sheet` actually reads.
EVAL_LINK_TRUE = frozenset({"y", "yes", "1", "true"})
EVAL_LINK_FALSE = frozenset({"n", "no", "0", "false"})
SENTIMENT_LABELS = frozenset({"positive", "neutral", "negative"})

# Display names only; never used to read a cell.
_COLUMN_TITLES = {
    "relevant": "relevant",
    "manual_link_ok": "linking",
    "manual_sentiment": "sentiment",
}


@dataclass(frozen=True)
class Problem:
    """One cell the scorer cannot use, located precisely enough to fix it."""

    row: int  # 1-based data row, header excluded
    column: str
    value: str
    reason: str


@dataclass
class SheetStatus:
    name: str
    path: Path
    exists: bool
    total: int = 0
    complete_rows: int = 0  # rows where every label column is usable
    # Which columns carry labels. Explicit rather than inferred from `name`, so
    # renaming a sheet cannot change how its progress is rendered.
    label_columns: tuple[str, ...] = ("relevant",)
    columns: dict[str, int] = field(default_factory=dict)  # column -> usable labels
    per_slot: dict[str, int] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.problems

    @property
    def remaining(self) -> int:
        """Rows still needing a label on at least one column."""
        return max(self.total - self.complete_rows, 0)

    def filled(self, column: str) -> int:
        return self.columns.get(column, 0)


def _read_rows(path: Path) -> list[dict[str, str]]:
    """Read a sheet, tolerating the encodings a spreadsheet export produces.

    Annotators will edit these in Excel/LibreOffice, and "CSV" from Excel on
    Windows is cp1252, not UTF-8. A `UnicodeDecodeError` traceback would look
    like the tool is broken when the file simply needs re-saving, so fall back
    and say so rather than crash. `utf-8-sig` also strips the BOM Excel writes,
    which would otherwise turn the first column name into "\ufeffrelevant" and
    silently hide every label in that column.
    """
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open(encoding=encoding, newline="") as fh:
                return list(csv.DictReader(fh))
        except UnicodeDecodeError:
            continue
    raise SystemExit(
        f"cannot decode {path}: re-save it as UTF-8 CSV. Nothing was counted."
    )


def _cell(row: dict[str, str], column: str) -> str:
    return (row.get(column) or "").strip()


def _classify(value: str, accepted: frozenset[str]) -> bool:
    """True when the cell holds one of `accepted`; blank and junk are both False."""
    return value.lower() in accepted


def _missing_column(rows: list[dict[str, str]], column: str, path: Path) -> Problem:
    """A renamed/absent label column is a file problem, not an empty sheet.

    Reading it as all-blank would report "0/100, ok" for a sheet that can never
    reach 100, and the report would look exactly like a team that has not started.
    `analyze.score_eval_sheet` raises KeyError on a missing column, so flagging it
    here also keeps this tool consistent with the scorer.
    """
    seen = ", ".join(sorted(rows[0].keys())) if rows else "(no header)"
    return Problem(
        row=0,
        column=column,
        value="",
        reason=f"column not found in {path.name}; found: {seen}",
    )


def check_relevance_sheet(
    name: str, path: Path = REVIEW_REDDIT, column: str = "relevant"
) -> SheetStatus:
    """Progress for a relevance sheet (`review_relevance*.csv`)."""
    status = SheetStatus(
        name=name, path=path, exists=path.exists(), label_columns=(column,)
    )
    if not status.exists:
        return status

    rows = _read_rows(path)
    status.total = len(rows)
    if rows and column not in rows[0]:
        status.problems.append(_missing_column(rows, column, path))
        return status
    usable = 0
    complete = 0
    for position, row in enumerate(rows, start=1):
        value = _cell(row, column)
        if not value:
            continue
        if _classify(value, RELEVANCE_TRUE) or _classify(value, RELEVANCE_FALSE):
            usable += 1
            complete += 1
            continue
        status.problems.append(
            Problem(
                row=position,
                column=column,
                value=value,
                reason="expected y/n (yes/no/1/0/true/false/relevan/tidak)",
            )
        )
    status.columns[column] = usable
    status.complete_rows = complete
    return status


def check_eval_sheet(name: str, path: Path = EVAL_SHEET) -> SheetStatus:
    """Progress for `eval_linking_sentiment.csv`, which has two label columns."""
    status = SheetStatus(
        name=name,
        path=path,
        exists=path.exists(),
        label_columns=("manual_link_ok", "manual_sentiment"),
    )
    if not status.exists:
        return status

    rows = _read_rows(path)
    status.total = len(rows)
    required = status.label_columns
    if rows:
        for column in required:
            if column not in rows[0]:
                status.problems.append(_missing_column(rows, column, path))
        if status.problems:
            return status
    link_ok = 0
    sentiment_ok = 0
    slots: dict[str, int] = {}

    for position, row in enumerate(rows, start=1):
        link = _cell(row, "manual_link_ok")
        sentiment = _cell(row, "manual_sentiment").lower()
        link_usable = False
        sentiment_usable = False

        if link:
            if _classify(link, EVAL_LINK_TRUE) or _classify(link, EVAL_LINK_FALSE):
                link_ok += 1
                link_usable = True
            else:
                # `relevan` is valid in the relevance sheets but not here; saying
                # so is the difference between a fixable typo and a mystery zero.
                hint = (
                    " (valid in the relevance sheets, ignored by the eval scorer: "
                    "use y/n)"
                    if link.lower() in RELEVANCE_TRUE | RELEVANCE_FALSE
                    else " (expected y/n)"
                )
                status.problems.append(
                    Problem(position, "manual_link_ok", link, f"unusable value{hint}")
                )

        if sentiment:
            if sentiment in SENTIMENT_LABELS:
                sentiment_ok += 1
                sentiment_usable = True
            else:
                status.problems.append(
                    Problem(
                        position,
                        "manual_sentiment",
                        sentiment,
                        "expected positive/neutral/negative",
                    )
                )

        # Per-annotator progress, so a member who has not started is visible
        # without asking them. A row counts only when both columns are usable.
        if link_usable and sentiment_usable:
            status.complete_rows += 1
            slot = _cell(row, "annotator_slot") or "?"
            slots[slot] = slots.get(slot, 0) + 1

    status.columns["manual_link_ok"] = link_ok
    status.columns["manual_sentiment"] = sentiment_ok
    status.per_slot = dict(sorted(slots.items()))
    return status


def check_all(
    reddit: Path = REVIEW_REDDIT,
    youtube: Path = REVIEW_YOUTUBE,
    eval_sheet: Path = EVAL_SHEET,
) -> list[SheetStatus]:
    return [
        check_relevance_sheet("Reddit relevance", reddit),
        check_relevance_sheet("YouTube relevance", youtube),
        check_eval_sheet("Eval linking + sentiment", eval_sheet),
    ]


def render(statuses: list[SheetStatus]) -> str:
    """Plain-text report; nothing here is written back to the sheets."""
    lines: list[str] = ["Manual labelling gate", ""]
    for status in statuses:
        if not status.exists:
            lines.append(f"  {status.name:<26} MISSING  {status.path}")
            continue
        if len(status.label_columns) > 1:
            detail = ", ".join(
                f"{_COLUMN_TITLES.get(column, column)} "
                f"{status.filled(column)}/{status.total}"
                for column in status.label_columns
            )
        else:
            detail = f"{status.filled(status.label_columns[0])}/{status.total}"
        state = "ok" if status.is_clean else f"{len(status.problems)} bad cell(s)"
        lines.append(f"  {status.name:<26} {detail:<34} [{state}]")
        if status.per_slot:
            lines.append(f"    per annotator (both columns filled): {status.per_slot}")
        for problem in status.problems[:10]:
            lines.append(
                f"    row {problem.row} `{problem.column}` = {problem.value!r}: {problem.reason}"
            )
        if len(status.problems) > 10:
            lines.append(f"    ... and {len(status.problems) - 10} more")

    blanks = [status.remaining for status in statuses if status.exists]
    lines.append("")
    if any(blanks):
        lines.append(
            "Status: still indicative. Labels are a human judgement; nothing here fills them."
        )
    else:
        lines.append("Status: every sheet is labelled and clean.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report progress and format problems for the manual labelling sheets."
    )
    parser.add_argument("--reddit", type=Path, default=REVIEW_REDDIT)
    parser.add_argument("--youtube", type=Path, default=REVIEW_YOUTUBE)
    parser.add_argument("--eval", dest="eval_sheet", type=Path, default=EVAL_SHEET)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(name)s: %(message)s")
    statuses = check_all(args.reddit, args.youtube, args.eval_sheet)
    sys.stdout.write(render(statuses))

    # A missing sheet is not a format error: `make review` may simply not have
    # run yet, and the gate is already reported as incomplete above.
    return 0 if all(status.is_clean for status in statuses) else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the Makefile
    raise SystemExit(main())
