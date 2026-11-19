"""Tests for the read-only external label sheet audit tool.

Covers negative cases (missing columns, unknown values, wrong-player sentences,
copied overlap blocks), boundary cases (L001-L012 vs L013+, blank/empty sheets,
`membahas_pemain = n` with blank sentiment), and the strict read-only contract
(nothing written to data/interim or data/processed).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.scrape import label_audit

SHEET_FIELDS = [
    "item_id",
    "pemain",
    "kalimat",
    "membahas_pemain",
    "sentimen",
    "aspek",
    "catatan",
    "konteks_komentar",
    "subreddit",
    "url",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


def _write_players(path: Path, players: list[tuple[str, str, str]]) -> Path:
    return _write_csv(
        path,
        ["player_id", "name_canonical", "name_aliases", "club"],
        [
            {"player_id": pid, "name_canonical": name, "name_aliases": name, "club": club}
            for pid, name, club in players
        ],
    )


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


# ------------------------------------------------------------------ boundary
@pytest.mark.parametrize(
    ("item_id", "expected"),
    [
        ("L000", False),
        ("L001", True),
        ("l005", True),
        ("L012", True),
        ("L013", False),
        ("L100", False),
        ("", False),
        ("X001", False),
        ("L012a", False),
    ],
)
def test_overlap_boundary_is_strictly_l001_to_l012(item_id: str, expected: bool) -> None:
    """Boundary check: L001-L012 are overlap; L000 and L013+ are not."""
    assert label_audit.is_overlap_item(item_id) is expected


def test_blank_and_header_only_sheets_report_zero_answered(tmp_path: Path) -> None:
    """Boundary: an all-blank sheet (like label_D) and a 0-row sheet do not crash."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    blank_sheet = _write_csv(
        tmp_path / "label_D.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L001",
                "pemain": "Bukayo Saka",
                "kalimat": "Saka was sharp today.",
                "membahas_pemain": "",
                "sentimen": "",
            },
            {
                "item_id": "L013",
                "pemain": "Bukayo Saka",
                "kalimat": "Saka tracked back well.",
                "membahas_pemain": "",
                "sentimen": "",
            },
        ],
    )
    empty_sheet = _write_csv(tmp_path / "label_empty.csv", SHEET_FIELDS, [])

    report = label_audit.audit_sheets([blank_sheet, empty_sheet], players_path=players)

    assert report.sheets[0].total_rows == 2
    assert report.sheets[0].answered_rows == 0
    assert report.sheets[0].overlap_total == 1
    assert report.sheets[0].non_overlap_total == 1
    assert report.sheets[1].total_rows == 0
    assert report.sheets[1].answered_rows == 0
    assert report.unmapped_reasons == {"blank_row": 2}


def test_negative_link_with_blank_sentiment_counts_as_answered_not_scorable(
    tmp_path: Path,
) -> None:
    """Following the spreadsheet instructions, `n` + blank sentiment is valid and skipped from sentiment scoring."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Matty Cash", "Aston Villa")])
    sheet = _write_csv(
        tmp_path / "label_B.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L015",
                "pemain": "Matty Cash",
                "kalimat": "At least we have a bit of cash this summer.",
                "membahas_pemain": "n",
                "sentimen": "",
            }
        ],
    )
    preds = _write_jsonl(
        tmp_path / "preds.jsonl",
        [
            {
                "text_id": "t1",
                "player_id": "p1",
                "unit_type": "sentence",
                "text_clean": "At least we have a bit of cash this summer.",
                "sentiment_label": "neutral",
                "sentiment_score": 0.0,
            }
        ],
    )

    report = label_audit.audit_sheets(
        [sheet], players_path=players, predictions_path=preds
    )

    assert report.sheets[0].answered_rows == 1
    assert report.sheets[0].invalid_cells == ()
    assert len(report.mapped_items) == 1
    assert report.mapped_items[0].agreement is None
    assert report.agreement_all_rows is not None
    assert report.agreement_all_rows.total == 0
    assert report.agreement_all_rows.rate is None


def test_overlap_and_non_overlap_affected_items_are_separated(tmp_path: Path) -> None:
    """Overlap L001-L012 and non-overlap L013+ must stay separate in counts and output."""
    players = _write_players(
        tmp_path / "players.csv",
        [
            ("p1", "Bart Verbruggen", "Brighton"),
            ("p2", "Bernd Leno", "Fulham"),
        ],
    )
    sheet_a = _write_csv(
        tmp_path / "label_A.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L005",
                "pemain": "Bart Verbruggen",
                "kalimat": "Verbruggen made a huge error today.",
                "membahas_pemain": "ya",
                "sentimen": "negatif",
            },
            {
                "item_id": "L013",
                "pemain": "Bernd Leno",
                "kalimat": "Leno saved us with two brilliant stops.",
                "membahas_pemain": "y",
                "sentimen": "positif",
            },
        ],
    )
    sheet_c = _write_csv(
        tmp_path / "label_C.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L005",
                "pemain": "Bart Verbruggen",
                "kalimat": "Verbruggen made a huge error today.",
                "membahas_pemain": "y",
                "sentimen": "negatif",
            },
            {
                "item_id": "L020",
                "pemain": "Bernd Leno",
                "kalimat": "Leno distribution was shaky all second half.",
                "membahas_pemain": "y",
                "sentimen": "negatif",
            },
        ],
    )
    preds = _write_jsonl(
        tmp_path / "text_analysis.jsonl",
        [
            {
                "text_id": "t_ov",
                "player_id": "p1",
                "unit_type": "sentence",
                "text_clean": "Verbruggen made a huge error today.",
                "sentiment_label": "neutral",  # mismatch with manual negative
                "sentiment_score": 0.0,
            },
            {
                "text_id": "t_no1",
                "player_id": "p2",
                "unit_type": "sentence",
                "text_clean": "Leno saved us with two brilliant stops.",
                "sentiment_label": "positive",  # match
                "sentiment_score": 0.8,
            },
            {
                "text_id": "t_no2",
                "player_id": "p2",
                "unit_type": "sentence",
                "text_clean": "Leno distribution was shaky all second half.",
                "sentiment_label": "negative",  # match
                "sentiment_score": -0.5,
            },
        ],
    )

    report = label_audit.audit_sheets(
        [sheet_a, sheet_c], players_path=players, predictions_path=preds
    )

    assert report.agreement_all_rows is not None
    assert report.agreement_overlap_rows is not None
    assert report.agreement_non_overlap_rows is not None
    assert report.agreement_unique_items is not None

    # All rows counts L005 twice (2/4 = 50%); unique dedupes L005 (2/3 = 66.7%);
    # overlap is 0/2 while non-overlap is 2/2 (100%).
    assert (report.agreement_all_rows.agreed, report.agreement_all_rows.total) == (2, 4)
    assert (report.agreement_overlap_rows.agreed, report.agreement_overlap_rows.total) == (0, 2)
    assert (
        report.agreement_non_overlap_rows.agreed,
        report.agreement_non_overlap_rows.total,
    ) == (2, 2)
    assert (report.agreement_unique_items.agreed, report.agreement_unique_items.total) == (2, 3)

    rendered = label_audit.render_report(report)
    assert "[Overlap (L001-L012)] (2 row(s))" in rendered
    assert "[Non-overlap (L013+)] (2 row(s))" in rendered
    assert "INDICATIVE ONLY" in rendered
    assert label_audit.MAPPING_METHOD in rendered


# ------------------------------------------------------------------ negative
def test_missing_required_column_fails_loudly(tmp_path: Path) -> None:
    """Negative case: a renamed or absent required column must fail, not silently yield zero."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    bad_sheet = _write_csv(
        tmp_path / "bad.csv",
        ["item_id", "pemain", "kalimat", "membahas_pemain"],  # missing `sentimen`
        [{"item_id": "L001", "pemain": "Bukayo Saka", "kalimat": "Saka scored.", "membahas_pemain": "y"}],
    )

    with pytest.raises(ValueError, match="sentimen"):
        label_audit.audit_sheets([bad_sheet], players_path=players)

    with pytest.raises(SystemExit, match="sentimen"):
        label_audit.main([str(bad_sheet), "--players", str(players)])


def test_missing_file_and_unsupported_extension_fail_loudly(tmp_path: Path) -> None:
    """Negative case: absent paths and unsupported extensions are rejected explicitly."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    with pytest.raises(FileNotFoundError):
        label_audit.audit_sheets([tmp_path / "does_not_exist.csv"], players_path=players)

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("not a spreadsheet", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported file format"):
        label_audit.audit_sheets([txt_file], players_path=players)


def test_invalid_label_values_are_flagged_and_never_scored(tmp_path: Path) -> None:
    """Negative case: unrecognised cells are logged as invalid and excluded from agreement."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    sheet = _write_csv(
        tmp_path / "label_bad_vals.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L014",
                "pemain": "Bukayo Saka",
                "kalimat": "Saka was unbelievable tonight.",
                "membahas_pemain": "mungkin",
                "sentimen": "mixed",
            }
        ],
    )
    preds = _write_jsonl(
        tmp_path / "preds.jsonl",
        [
            {
                "text_id": "t1",
                "player_id": "p1",
                "unit_type": "sentence",
                "text_clean": "Saka was unbelievable tonight.",
                "sentiment_label": "positive",
            }
        ],
    )

    report = label_audit.audit_sheets(
        [sheet], players_path=players, predictions_path=preds
    )

    assert len(report.sheets[0].invalid_cells) == 2
    assert report.sheets[0].answered_rows == 0
    assert report.mapped_items == ()
    assert report.agreement_all_rows is not None
    assert report.agreement_all_rows.total == 0


def test_same_sentence_under_wrong_player_is_not_mapped(tmp_path: Path) -> None:
    """Negative case: name_canonical -> player_id disambiguation prevents cross-player mismatch."""
    players = _write_players(
        tmp_path / "players.csv",
        [
            ("p1", "Bukayo Saka", "Arsenal"),
            ("p2", "Martin Odegaard", "Arsenal"),
        ],
    )
    sheet = _write_csv(
        tmp_path / "label_X.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L015",
                "pemain": "Bukayo Saka",
                "kalimat": "Great pressing from the front line today.",
                "membahas_pemain": "y",
                "sentimen": "positif",
            },
            {
                "item_id": "L016",
                "pemain": "Harry Maguire",  # not in locked sample
                "kalimat": "Maguire won every aerial duel.",
                "membahas_pemain": "y",
                "sentimen": "positif",
            },
        ],
    )
    # The sentence belongs to p2 (Odegaard), not p1 (Saka).
    corpus = _write_jsonl(
        tmp_path / "corpus.jsonl",
        [
            {
                "text_id": "t_p2",
                "player_id": "p2",
                "unit_type": "sentence",
                "text_clean": "Great pressing from the front line today.",
            }
        ],
    )

    report = label_audit.audit_sheets([sheet], players_path=players, corpus_path=corpus)

    assert report.mapped_items == ()
    assert report.unmapped_reasons["text_not_in_corpus"] == 1
    assert report.unmapped_reasons["player_not_in_sample"] == 1
    assert report.sheets[0].out_of_sample_players == ("Harry Maguire",)


def test_copied_overlap_is_flagged_as_not_valid_for_kappa(tmp_path: Path) -> None:
    """Negative case: near-identical L001-L012 answers trigger a copy warning."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    rows_c = [
        {
            "item_id": f"L{i:03d}",
            "pemain": "Bukayo Saka",
            "kalimat": f"Sentence number {i} about Saka.",
            "membahas_pemain": "y",
            "sentimen": "netral" if i % 2 else "positif",
            "aspek": "passing",
        }
        for i in range(1, 13)
    ]
    rows_a = [dict(r) for r in rows_c]
    rows_a[0]["sentimen"] = "negatif"  # 11/12 identical — mirrors handoff finding

    sheet_a = _write_csv(tmp_path / "label_A.csv", SHEET_FIELDS, rows_a)
    sheet_c = _write_csv(tmp_path / "label_C.csv", SHEET_FIELDS, rows_c)

    report = label_audit.audit_sheets([sheet_a, sheet_c], players_path=players)

    assert len(report.overlap_checks) == 1
    check = report.overlap_checks[0]
    assert check.shared_answered == 12
    assert check.identical_decisions == 11
    assert check.possible_copy is True
    assert any("Cohen's kappa" in w for w in report.warnings)


def test_conflicting_manual_sentiments_excluded_from_unique_rate(tmp_path: Path) -> None:
    """When two annotators disagree on one overlap item, unique-item rate does not pick a side."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    row_base = {
        "item_id": "L002",
        "pemain": "Bukayo Saka",
        "kalimat": "Saka looked tired late on.",
        "membahas_pemain": "y",
    }
    sheet_b = _write_csv(
        tmp_path / "label_B.csv", SHEET_FIELDS, [{**row_base, "sentimen": "negatif"}]
    )
    sheet_c = _write_csv(
        tmp_path / "label_C.csv", SHEET_FIELDS, [{**row_base, "sentimen": "netral"}]
    )
    preds = _write_jsonl(
        tmp_path / "preds.jsonl",
        [
            {
                "text_id": "t2",
                "player_id": "p1",
                "unit_type": "sentence",
                "text_clean": "Saka looked tired late on.",
                "sentiment_label": "negative",
            }
        ],
    )

    report = label_audit.audit_sheets(
        [sheet_b, sheet_c], players_path=players, predictions_path=preds
    )

    assert report.agreement_unique_items is not None
    assert report.agreement_unique_items.total == 0
    assert report.agreement_unique_items.conflicting_items == ("L002",)
    assert any("conflicts" in w for w in report.warnings)


def test_audit_is_strictly_read_only_and_never_writes_to_data_dirs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI must never create or modify any file under data/interim or data/processed."""
    interim = tmp_path / "data" / "interim"
    processed = tmp_path / "data" / "processed"
    players = _write_players(processed / "text_sample.parquet.csv", [("p1", "Bukayo Saka", "Arsenal")])
    corpus = _write_jsonl(
        interim / "texts_reddit_full.jsonl",
        [
            {
                "text_id": "t1",
                "player_id": "p1",
                "unit_type": "sentence",
                "text_clean": "Saka controlled the right flank.",
            }
        ],
    )
    eval_csv = _write_csv(
        interim / "eval_linking_sentiment.csv",
        ["eval_idx", "text_id", "text_clean", "manual_link_ok", "manual_sentiment"],
        [{"eval_idx": "1", "text_id": "t1", "text_clean": "Saka controlled the right flank."}],
    )
    sheet = _write_csv(
        tmp_path / "label_B.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L018",
                "pemain": "Bukayo Saka",
                "kalimat": "Saka controlled the right flank.",
                "membahas_pemain": "y",
                "sentimen": "positif",
            }
        ],
    )

    def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
        return {
            str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))
            if p.is_file()
        }

    before = _snapshot(tmp_path)
    code = label_audit.main(
        [
            str(sheet),
            "--players",
            str(players),
            "--corpus",
            str(corpus),
            "--eval-sheet",
            str(eval_csv),
            "--json",
        ]
    )
    after = _snapshot(tmp_path)

    assert code == 0
    assert before == after, "audit tool must not create or mutate any file on disk"
    payload = json.loads(capsys.readouterr().out)
    assert payload["mapping_method"] == label_audit.MAPPING_METHOD
    assert payload["gate_intersection"]["matched_sentences_total"] == 1
    assert payload["gate_intersection"]["matched_answered_rows"] == 1


# ----------------------------------------------------------------- xlsx & gate
def test_xlsx_sheet_reading_prefers_lembar_tab(tmp_path: Path) -> None:
    """Real .xlsx workbook with Petunjuk + Lembar tabs reads Lembar cleanly."""
    openpyxl = pytest.importorskip("openpyxl")

    wb = openpyxl.Workbook()
    ws_guide = wb.active
    ws_guide.title = "Petunjuk"
    ws_guide.append(["Petunjuk pengisian"])

    ws_data = wb.create_sheet("Lembar")
    ws_data.append(SHEET_FIELDS)
    ws_data.append(
        [
            "L005",
            "Bart Verbruggen",
            "Verbruggen made a great save.",
            "y",
            "positif",
            "tidak ada",
            None,
            "Verbruggen made a great save.",
            "BrightonHoveAlbion",
            "https://example.test/1",
        ]
    )
    ws_data.append(
        [
            "L030",
            "Bart Verbruggen",
            "Verbruggen might attract interest.",
            "y",
            "netral",
            "tidak ada",
            None,
            "Verbruggen might attract interest.",
            "BrightonHoveAlbion",
            "https://example.test/2",
        ]
    )
    xlsx_path = tmp_path / "label_B.xlsx"
    wb.save(xlsx_path)
    wb.close()

    rows, invalid = label_audit.read_label_sheet(xlsx_path)

    assert invalid == []
    assert len(rows) == 2
    assert rows[0].item_id == "L005"
    assert rows[0].is_overlap is True
    assert rows[0].sentiment_label == "positive"
    assert rows[1].item_id == "L030"
    assert rows[1].is_overlap is False
    assert rows[1].sentiment_label == "neutral"


def test_gate_intersection_separates_answered_from_blank_matches(tmp_path: Path) -> None:
    """Mirrors handoff CMD-05: a sentence matching only an unlabelled row is counted as blank."""
    players = _write_players(tmp_path / "players.csv", [("p1", "Bukayo Saka", "Arsenal")])
    sheet_d = _write_csv(
        tmp_path / "label_D.csv",
        SHEET_FIELDS,
        [
            {
                "item_id": "L099",
                "pemain": "Bukayo Saka",
                "kalimat": "Saka never hides in big matches.",
                "membahas_pemain": "",
                "sentimen": "",
            }
        ],
    )
    eval_sheet = _write_csv(
        tmp_path / "eval_linking_sentiment.csv",
        ["eval_idx", "text_id", "text_clean", "manual_link_ok", "manual_sentiment"],
        [
            {"eval_idx": "1", "text_id": "t1", "text_clean": "Saka never hides in big matches."},
            {"eval_idx": "2", "text_id": "t2", "text_clean": "Unrelated sentence."},
        ],
    )

    report = label_audit.audit_sheets(
        [sheet_d], players_path=players, eval_sheet_path=eval_sheet
    )

    assert report.gate_intersection is not None
    assert report.gate_intersection.matched_sentences_total == 1
    assert report.gate_intersection.matched_answered_rows == 0
    assert report.gate_intersection.matched_blank_rows == 1
    assert report.gate_intersection.matched_item_ids == ("L099",)
