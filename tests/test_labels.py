"""Tests for the manual labelling status report.

The point of this module is to be boring and honest: it must never turn a
value it does not understand into a label, because the number it reports feeds
the human-evaluation gate. Most of these tests exist to pin that refusal.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.scrape import labels, relevance


def write_sheet(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


REVIEW_FIELDS = ["text_id", "player_id", "text_clean", "relevant"]
EVAL_FIELDS = [
    "eval_idx",
    "annotator_slot",
    "text_id",
    "manual_link_ok",
    "manual_sentiment",
]


# ------------------------------------------------------------------ relevance
def test_blank_sheet_reports_zero_and_is_clean(tmp_path: Path) -> None:
    path = write_sheet(
        tmp_path / "review.csv",
        REVIEW_FIELDS,
        [{"text_id": f"t{i}", "relevant": ""} for i in range(3)],
    )

    status = labels.check_relevance_sheet("Reddit", path)

    assert status.exists
    assert status.total == 3
    assert status.filled("relevant") == 0
    assert status.remaining == 3
    assert status.is_clean, "a blank sheet is incomplete, not malformed"


def test_missing_sheet_is_reported_not_raised(tmp_path: Path) -> None:
    status = labels.check_relevance_sheet("Reddit", tmp_path / "nope.csv")

    assert status.exists is False
    assert status.total == 0
    assert status.is_clean


@pytest.mark.parametrize("value", ["mungkin", "kadang", "?", "yaa"])
def test_unrecognised_value_is_a_problem_and_never_counted(
    tmp_path: Path, value: str
) -> None:
    path = write_sheet(tmp_path / "review.csv", REVIEW_FIELDS, [{"relevant": value}])

    status = labels.check_relevance_sheet("Reddit", path)

    assert status.filled("relevant") == 0, "an unknown value must not be counted"
    assert len(status.problems) == 1
    assert status.problems[0].value == value
    assert status.problems[0].row == 1
    assert not status.is_clean


def test_partially_filled_sheet_counts_only_usable_values(tmp_path: Path) -> None:
    path = write_sheet(
        tmp_path / "review.csv",
        REVIEW_FIELDS,
        [
            {"relevant": "y"},
            {"relevant": ""},
            {"relevant": "tidak"},
            {"relevant": "mungkin"},
        ],
    )

    status = labels.check_relevance_sheet("Reddit", path)

    assert status.filled("relevant") == 2
    assert status.complete_rows == 2
    assert status.remaining == 2, "blank and malformed rows both still need work"
    assert len(status.problems) == 1


def test_every_accepted_relevance_value_matches_the_scorer() -> None:
    """The two vocabularies must not drift: this is the equivalence test.

    `relevance._parse_label` is what actually scores the sheet, so any value
    this module calls usable must parse there too, and vice versa.
    """
    for value in labels.RELEVANCE_TRUE:
        assert relevance._parse_label(value) is True
    for value in labels.RELEVANCE_FALSE:
        assert relevance._parse_label(value) is False

    rejected = ["mungkin", "?", "neutral", ""]
    for value in rejected:
        assert relevance._parse_label(value) is None


# ----------------------------------------------------------------- eval sheet
def test_eval_sheet_counts_both_columns(tmp_path: Path) -> None:
    path = write_sheet(
        tmp_path / "eval.csv",
        EVAL_FIELDS,
        [
            {"annotator_slot": "A", "manual_link_ok": "y", "manual_sentiment": "positive"},
            {"annotator_slot": "A", "manual_link_ok": "n", "manual_sentiment": ""},
            {"annotator_slot": "B", "manual_link_ok": "", "manual_sentiment": "neutral"},
        ],
    )

    status = labels.check_eval_sheet("Eval", path)

    assert status.filled("manual_link_ok") == 2
    assert status.filled("manual_sentiment") == 2
    assert status.complete_rows == 1, "only the first row has both columns usable"
    assert status.remaining == 2
    assert status.per_slot == {"A": 1}
    assert status.is_clean


def test_eval_sheet_rejects_relevance_only_vocabulary(tmp_path: Path) -> None:
    """`relevan` is legal in the relevance sheets but the eval scorer ignores it.

    Silently accepting it would report progress the scorer cannot use.
    """
    path = write_sheet(
        tmp_path / "eval.csv",
        EVAL_FIELDS,
        [{"annotator_slot": "A", "manual_link_ok": "relevan", "manual_sentiment": "positive"}],
    )

    status = labels.check_eval_sheet("Eval", path)

    assert status.filled("manual_link_ok") == 0
    assert len(status.problems) == 1
    assert "y/n" in status.problems[0].reason


def test_eval_sheet_rejects_unknown_sentiment(tmp_path: Path) -> None:
    path = write_sheet(
        tmp_path / "eval.csv",
        EVAL_FIELDS,
        [{"annotator_slot": "A", "manual_link_ok": "y", "manual_sentiment": "mixed"}],
    )

    status = labels.check_eval_sheet("Eval", path)

    assert status.filled("manual_sentiment") == 0
    assert len(status.problems) == 1
    assert status.complete_rows == 0


# ------------------------------------------------------------------- boundary
def test_main_exit_code_is_zero_when_sheets_are_empty_but_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reddit = write_sheet(tmp_path / "r.csv", REVIEW_FIELDS, [{"relevant": ""}])
    youtube = write_sheet(tmp_path / "y.csv", REVIEW_FIELDS, [{"relevant": ""}])
    eval_sheet = write_sheet(tmp_path / "e.csv", EVAL_FIELDS, [{"manual_link_ok": ""}])

    code = labels.main(
        ["--reddit", str(reddit), "--youtube", str(youtube), "--eval", str(eval_sheet)]
    )

    assert code == 0, "nothing is malformed, the work is simply not done yet"
    assert "still indicative" in capsys.readouterr().out


def test_main_exit_code_is_one_when_any_cell_is_unusable(tmp_path: Path) -> None:
    reddit = write_sheet(tmp_path / "r.csv", REVIEW_FIELDS, [{"relevant": "mungkin"}])
    youtube = write_sheet(tmp_path / "y.csv", REVIEW_FIELDS, [{"relevant": ""}])
    eval_sheet = write_sheet(tmp_path / "e.csv", EVAL_FIELDS, [{"manual_link_ok": ""}])

    code = labels.main(
        ["--reddit", str(reddit), "--youtube", str(youtube), "--eval", str(eval_sheet)]
    )

    assert code == 1


def test_main_exit_code_is_zero_when_every_sheet_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = labels.main(
        [
            "--reddit",
            str(tmp_path / "a.csv"),
            "--youtube",
            str(tmp_path / "b.csv"),
            "--eval",
            str(tmp_path / "c.csv"),
        ]
    )

    assert code == 0
    assert capsys.readouterr().out.count("MISSING") == 3


def test_report_lists_at_most_ten_problems(tmp_path: Path) -> None:
    path = write_sheet(
        tmp_path / "review.csv",
        REVIEW_FIELDS,
        [{"relevant": "mungkin"} for _ in range(15)],
    )

    status = labels.check_relevance_sheet("Reddit", path)
    text = labels.render([status])

    assert len(status.problems) == 15
    assert "... and 5 more" in text


# ------------------------------------------------------- reviewer concerns
def test_renamed_label_column_is_a_problem_not_a_blank_sheet(tmp_path: Path) -> None:
    """A missing column must not read as "0/100, ok".

    That report is indistinguishable from a team that has not started, and
    `analyze.score_eval_sheet` raises KeyError on the same file, so treating it
    as blank would make this tool disagree with the scorer.
    """
    path = tmp_path / "review.csv"
    path.write_text("text_id,player_id,Relevan\nt1,p1,y\n", encoding="utf-8")

    status = labels.check_relevance_sheet("Reddit", path)

    assert status.filled("relevant") == 0
    assert len(status.problems) == 1
    assert "column not found" in status.problems[0].reason
    assert not status.is_clean


def test_eval_sheet_missing_a_label_column_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "eval.csv"
    path.write_text("eval_idx,annotator_slot,text_id\n1,A,t1\n", encoding="utf-8")

    status = labels.check_eval_sheet("Eval", path)

    assert not status.is_clean
    assert len(status.problems) == 2, "both label columns are absent"


def test_cp1252_sheet_is_read_instead_of_crashing(tmp_path: Path) -> None:
    """Excel on Windows writes cp1252, not UTF-8. A crash would look like a bug."""
    path = tmp_path / "review.csv"
    # 0x92 is a right single quote in cp1252 and invalid as standalone UTF-8.
    path.write_bytes(
        b"text_id,player_id,text_clean,relevant\n"
        b"t1,p1,Andr\xe9 played well,y\n"
    )

    status = labels.check_relevance_sheet("Reddit", path)

    assert status.filled("relevant") == 1
    assert status.is_clean


def test_utf8_bom_header_does_not_hide_labels(tmp_path: Path) -> None:
    """Excel writes a BOM; without utf-8-sig the column name becomes "\\ufeffrelevant"."""
    path = tmp_path / "review.csv"
    path.write_text("text_id,relevant\nt1,y\nt2,n\n", encoding="utf-8-sig")

    status = labels.check_relevance_sheet("Reddit", path)

    assert status.filled("relevant") == 2
    assert status.is_clean


def test_render_uses_the_declared_columns_not_the_sheet_name(tmp_path: Path) -> None:
    """Renaming a sheet must not change how its progress is rendered."""
    path = write_sheet(
        tmp_path / "eval.csv",
        EVAL_FIELDS,
        [{"annotator_slot": "A", "manual_link_ok": "y", "manual_sentiment": "positive"}],
    )
    status = labels.check_eval_sheet("Anything at all", path)

    text = labels.render([status])

    assert "linking 1/1" in text
    assert "sentiment 1/1" in text


def test_missing_sheets_are_never_reported_as_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty workspace must not print "every sheet is labelled and clean".

    The previous version filtered missing sheets out of the remaining-rows count,
    so three absent files produced a clean bill of health - the single most
    misleading line this tool could emit, and the exact opposite of what an
    unlabeled gate means.
    """
    code = labels.main(
        [
            "--reddit",
            str(tmp_path / "a.csv"),
            "--youtube",
            str(tmp_path / "b.csv"),
            "--eval",
            str(tmp_path / "c.csv"),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "clean" not in out
    assert "3 sheet(s) missing" in out
    assert "Nothing is labelled" in out
