"""Read-only audit tool for external team labelling sheets.

The team annotated external `.xlsx`/`.csv` sheets (`label_A`..`label_D`) that
were drawn from an earlier scrape before `text_sample.parquet` was re-locked.
Because their sentence intersection with the official evaluation gate
(`data/interim/eval_linking_sentiment.csv`) is near zero, those sheets must
never be imported into the gate CSVs.

This module inspects those sheets without writing anything to disk:

  * separates overlap rows (`L001`-`L012`) from non-overlap rows (`L013+`)
    everywhere, so copied overlap rows cannot silently inflate sample counts
    or agreement rates
  * maps rows to repository `text_id` values via explicit `name_canonical` ->
    `player_id` disambiguation against the locked sample (AGENTS.md rules 4
    and 17), naming the mapping method in every report
  * flags near-identical overlap blocks between sheets so copied answers are
    never reported as inter-annotator reliability (Cohen's kappa)
  * lists affected items that map to model sentiment predictions (when
    supplied), keeping overlap, non-overlap, and unique-item counts separate
    and explicitly marking every outside-gate number as indicative only

`openpyxl` is imported lazily inside the `.xlsx` reader so the rest of the
codebase stays runnable without adding a new required dependency.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from src.scrape.players import DEFAULT_PLAYERS, Player, load_players

log = logging.getLogger("labels.audit")

MAPPING_METHOD = "text_clean + name_canonical -> player_id (locked sample)"

OVERLAP_MIN = 1
OVERLAP_MAX = 12
_ITEM_ID_RE = re.compile(r"^L(\d+)$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")

REQUIRED_COLUMNS = (
    "item_id",
    "pemain",
    "kalimat",
    "membahas_pemain",
    "sentimen",
)

LINK_TRUE = frozenset({"y", "yes", "1", "true", "relevan", "relevant", "ya"})
LINK_FALSE = frozenset({"n", "no", "0", "false", "tidak", "not relevant"})
LINK_UNCERTAIN = frozenset({"ragu", "ragu-ragu", "unsure", "unclear"})

SENTIMENT_MAP: dict[str, str] = {
    "positif": "positive",
    "positive": "positive",
    "pos": "positive",
    "netral": "neutral",
    "neutral": "neutral",
    "neu": "neutral",
    "negatif": "negative",
    "negative": "negative",
    "neg": "negative",
}

COPY_MIN_SHARED = 6
COPY_SIMILARITY_THRESHOLD = 0.90


def _norm_text(text: str | None) -> str:
    return _WHITESPACE.sub(" ", (text or "").strip()).casefold()


def _norm_name(name: str | None) -> str:
    return _WHITESPACE.sub(" ", (name or "").strip()).casefold()


def _cell_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def is_overlap_item(item_id: str | None) -> bool:
    """True strictly for overlap IDs `L001` through `L012`."""
    match = _ITEM_ID_RE.match((item_id or "").strip())
    if not match:
        return False
    number = int(match.group(1))
    return OVERLAP_MIN <= number <= OVERLAP_MAX


def parse_link_label(value: str | None) -> str | None:
    """Return 'yes', 'no', 'uncertain', 'invalid', or None for blank."""
    raw = _cell_str(value).lower()
    if not raw:
        return None
    if raw in LINK_TRUE:
        return "yes"
    if raw in LINK_FALSE:
        return "no"
    if raw in LINK_UNCERTAIN:
        return "uncertain"
    return "invalid"


def parse_sentiment_label(value: str | None) -> str | None:
    """Normalise Indonesian/English sentiment to positive/neutral/negative."""
    raw = _cell_str(value).lower()
    if not raw:
        return None
    return SENTIMENT_MAP.get(raw, "invalid")


@dataclass(frozen=True)
class SheetRow:
    """One row read from an external annotator sheet."""

    sheet: str
    row_number: int  # 1-based data row, header excluded
    item_id: str
    is_overlap: bool
    player_name: str
    sentence: str
    link_raw: str
    link_label: str | None
    sentiment_raw: str
    sentiment_label: str | None
    aspect: str = ""
    url: str = ""
    subreddit: str = ""

    @property
    def is_answered(self) -> bool:
        """True when a human entered any usable answer on this row.

        Following the spreadsheet instructions, an annotator who marks
        `membahas_pemain = n` leaves `sentimen` blank; that still counts as a
        completed human decision.
        """
        return self.link_label in {"yes", "no", "uncertain"} or self.sentiment_label in {
            "positive",
            "neutral",
            "negative",
        }

    @property
    def is_sentiment_scorable(self) -> bool:
        """Only rows confirmed about the player with a valid sentiment label."""
        return self.link_label == "yes" and self.sentiment_label in {
            "positive",
            "neutral",
            "negative",
        }


@dataclass(frozen=True)
class InvalidCell:
    sheet: str
    row_number: int
    item_id: str
    column: str
    value: str


@dataclass(frozen=True)
class SheetSummary:
    sheet: str
    path: str
    total_rows: int
    answered_rows: int
    overlap_total: int
    overlap_answered: int
    non_overlap_total: int
    non_overlap_answered: int
    link_counts: dict[str, int]
    sentiment_counts: dict[str, int]
    in_locked_sample_rows: int
    in_locked_sample_players: int
    out_of_sample_players: tuple[str, ...]
    invalid_cells: tuple[InvalidCell, ...]


@dataclass(frozen=True)
class OverlapPairCheck:
    sheet_a: str
    sheet_b: str
    shared_answered: int
    identical_decisions: int
    identical_with_aspect: int
    decision_agreement: float
    possible_copy: bool


@dataclass(frozen=True)
class CorpusMatch:
    text_id: str
    player_id: str
    unit_type: str
    url: str


@dataclass(frozen=True)
class MappedItem:
    """One answered sheet row resolved to a repository `text_id`."""

    sheet: str
    item_id: str
    is_overlap: bool
    player_id: str
    player_name: str
    text_id: str
    unit_type: str
    link_label: str | None
    manual_sentiment: str | None
    model_sentiment: str | None
    model_score: float | None
    agreement: bool | None
    sentence_preview: str


@dataclass(frozen=True)
class AgreementBreakdown:
    total: int
    agreed: int
    rate: float | None
    conflicting_items: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateIntersection:
    eval_sheet_path: str
    eval_total_rows: int
    matched_sentences_total: int
    matched_answered_rows: int
    matched_blank_rows: int
    matched_overlap_rows: int
    matched_non_overlap_rows: int
    matched_item_ids: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    mapping_method: str
    players_path: str
    corpus_path: str | None
    predictions_path: str | None
    sheets: tuple[SheetSummary, ...]
    overlap_checks: tuple[OverlapPairCheck, ...]
    mapped_items: tuple[MappedItem, ...]
    unmapped_reasons: dict[str, int]
    agreement_all_rows: AgreementBreakdown | None
    agreement_overlap_rows: AgreementBreakdown | None
    agreement_non_overlap_rows: AgreementBreakdown | None
    agreement_unique_items: AgreementBreakdown | None
    gate_intersection: GateIntersection | None
    warnings: tuple[str, ...] = field(default_factory=tuple)


# -------------------------------------------------------------------- readers
def _validate_headers(headers: Sequence[str], path: Path) -> None:
    present = {h.strip() for h in headers if h}
    missing = [col for col in REQUIRED_COLUMNS if col not in present]
    if missing:
        raise ValueError(
            f"{path.name}: missing required column(s): {', '.join(missing)}"
        )


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                reader = csv.DictReader(fh)
                if reader.fieldnames is None:
                    raise ValueError(f"{path.name}: empty file with no header row")
                _validate_headers(reader.fieldnames, path)
                return list(reader)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: cannot decode CSV as UTF-8, cp1252, or latin-1")


def _read_xlsx_dicts(path: Path, sheet_name: str = "Lembar") -> list[dict[str, object]]:
    try:
        import openpyxl  # lazy import: not yet pinned in requirements.txt
    except ImportError as exc:
        raise SystemExit(
            f"cannot read {path.name}: `openpyxl` is not installed. "
            "Install openpyxl in your virtualenv or convert the sheet to CSV."
        ) from exc

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            raw_headers = next(rows_iter)
        except StopIteration as exc:
            raise ValueError(f"{path.name}: worksheet {ws.title!r} is empty") from exc
        headers = [_cell_str(cell) for cell in raw_headers]
        _validate_headers(headers, path)
        records: list[dict[str, object]] = []
        for values in rows_iter:
            if not any(v is not None and _cell_str(v) != "" for v in values):
                continue
            record = {
                headers[idx]: values[idx] if idx < len(values) else None
                for idx in range(len(headers))
                if headers[idx]
            }
            records.append(record)
        return records
    finally:
        wb.close()


def read_label_sheet(path: Path | str, sheet_label: str | None = None) -> tuple[list[SheetRow], list[InvalidCell]]:
    """Read one `.xlsx` or `.csv` annotator sheet without modifying it."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"label sheet not found: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix == ".xlsx":
        raw_rows = _read_xlsx_dicts(file_path)
    elif suffix == ".csv":
        raw_rows = _read_csv_dicts(file_path)
    else:
        raise ValueError(
            f"{file_path.name}: unsupported file format {suffix!r} (expected .xlsx or .csv)"
        )

    label = sheet_label or file_path.stem
    parsed: list[SheetRow] = []
    invalid: list[InvalidCell] = []
    for idx, raw in enumerate(raw_rows, start=1):
        item_id = _cell_str(raw.get("item_id"))
        player_name = _cell_str(raw.get("pemain"))
        sentence = _cell_str(raw.get("kalimat"))
        link_raw = _cell_str(raw.get("membahas_pemain"))
        sent_raw = _cell_str(raw.get("sentimen"))
        link_label = parse_link_label(link_raw)
        sent_label = parse_sentiment_label(sent_raw)

        if link_label == "invalid":
            invalid.append(InvalidCell(label, idx, item_id, "membahas_pemain", link_raw))
        if sent_label == "invalid":
            invalid.append(InvalidCell(label, idx, item_id, "sentimen", sent_raw))

        parsed.append(
            SheetRow(
                sheet=label,
                row_number=idx,
                item_id=item_id,
                is_overlap=is_overlap_item(item_id),
                player_name=player_name,
                sentence=sentence,
                link_raw=link_raw,
                link_label=link_label,
                sentiment_raw=sent_raw,
                sentiment_label=sent_label,
                aspect=_cell_str(raw.get("aspek")),
                url=_cell_str(raw.get("url")),
                subreddit=_cell_str(raw.get("subreddit")),
            )
        )
    return parsed, invalid


def _load_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        frame = pd.read_parquet(path)
        return frame.to_dict(orient="records")
    if suffix == ".jsonl":
        records: list[dict[str, object]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(json.loads(line))
        return records
    if suffix == ".csv":
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                with path.open("r", encoding=encoding, newline="") as fh:
                    return list(csv.DictReader(fh))
            except UnicodeDecodeError:
                continue
        raise ValueError(f"{path.name}: cannot decode CSV")
    raise ValueError(
        f"{path.name}: unsupported data format {suffix!r} (expected .parquet, .jsonl, or .csv)"
    )


def _build_player_name_index(players: Sequence[Player]) -> tuple[dict[str, str], set[str]]:
    """Map normalised `name_canonical` -> `player_id`, withholding collisions."""
    by_name: dict[str, list[str]] = defaultdict(list)
    for player in players:
        by_name[_norm_name(player.name)].append(player.player_id)
    unique: dict[str, str] = {}
    ambiguous: set[str] = set()
    for key, pids in by_name.items():
        if len(pids) == 1:
            unique[key] = pids[0]
        else:
            ambiguous.add(key)
    return unique, ambiguous


def _build_corpus_index(
    records: Iterable[dict[str, object]],
) -> dict[tuple[str, str], CorpusMatch]:
    """Index corpus rows by `(player_id, normalised_text_clean)`.

    When the same sentence exists both as a `comment` and a `sentence`, prefer
    `sentence` because Stage D scores sentences and external sheets are one
    sentence per row.
    """
    candidates: dict[tuple[str, str], list[CorpusMatch]] = defaultdict(list)
    for rec in records:
        pid = _cell_str(rec.get("player_id"))
        tid = _cell_str(rec.get("text_id"))
        text = _norm_text(_cell_str(rec.get("text_clean")))
        if not pid or not tid or not text:
            continue
        unit_type = _cell_str(rec.get("unit_type")) or "sentence"
        url = _cell_str(rec.get("url"))
        candidates[(pid, text)].append(CorpusMatch(tid, pid, unit_type, url))

    chosen: dict[tuple[str, str], CorpusMatch] = {}
    for key, matches in candidates.items():
        matches.sort(key=lambda m: (0 if m.unit_type == "sentence" else 1, m.text_id))
        chosen[key] = matches[0]
    return chosen


def _build_prediction_index(
    records: Iterable[dict[str, object]],
) -> dict[tuple[str, str], tuple[str, float | None]]:
    """Index model sentiment predictions by `(player_id, text_id)`."""
    preds: dict[tuple[str, str], tuple[str, float | None]] = {}
    for rec in records:
        pid = _cell_str(rec.get("player_id"))
        tid = _cell_str(rec.get("text_id"))
        sent = parse_sentiment_label(_cell_str(rec.get("sentiment_label")))
        if not pid or not tid or sent not in {"positive", "neutral", "negative"}:
            continue
        raw_score = rec.get("sentiment_score")
        score: float | None
        if raw_score is None or (isinstance(raw_score, float) and pd.isna(raw_score)) or str(raw_score).strip() == "":
            score = None
        else:
            score = float(raw_score)
        preds[(pid, tid)] = (sent, score)
    return preds


def _check_overlap_pairs(
    sheets_rows: dict[str, list[SheetRow]],
) -> list[OverlapPairCheck]:
    """Compare answered overlap rows (`L001`-`L012`) between every sheet pair."""
    names = sorted(sheets_rows)
    checks: list[OverlapPairCheck] = []
    overlap_maps: dict[str, dict[str, SheetRow]] = {}
    for name in names:
        overlap_maps[name] = {
            row.item_id.upper(): row
            for row in sheets_rows[name]
            if row.is_overlap and row.is_answered
        }

    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            shared_ids = sorted(set(overlap_maps[name_a]) & set(overlap_maps[name_b]))
            if not shared_ids:
                continue
            same_decision = 0
            same_with_aspect = 0
            for item_id in shared_ids:
                row_a = overlap_maps[name_a][item_id]
                row_b = overlap_maps[name_b][item_id]
                if (row_a.link_label, row_a.sentiment_label) == (
                    row_b.link_label,
                    row_b.sentiment_label,
                ):
                    same_decision += 1
                    if _norm_text(row_a.aspect) == _norm_text(row_b.aspect):
                        same_with_aspect += 1
            rate = same_decision / len(shared_ids)
            possible_copy = (
                len(shared_ids) >= COPY_MIN_SHARED and rate >= COPY_SIMILARITY_THRESHOLD
            )
            checks.append(
                OverlapPairCheck(
                    sheet_a=name_a,
                    sheet_b=name_b,
                    shared_answered=len(shared_ids),
                    identical_decisions=same_decision,
                    identical_with_aspect=same_with_aspect,
                    decision_agreement=rate,
                    possible_copy=possible_copy,
                )
            )
    return checks


def _agreement_for(items: Sequence[MappedItem]) -> AgreementBreakdown:
    scorable = [item for item in items if item.agreement is not None]
    total = len(scorable)
    agreed = sum(1 for item in scorable if item.agreement)
    return AgreementBreakdown(
        total=total,
        agreed=agreed,
        rate=(agreed / total) if total else None,
    )


def _unique_item_agreement(items: Sequence[MappedItem]) -> AgreementBreakdown:
    """Deduplicate affected items by `item_id`, flagging label disagreements."""
    by_id: dict[str, list[MappedItem]] = defaultdict(list)
    for item in items:
        if item.agreement is not None:
            by_id[item.item_id.upper()].append(item)

    agreed = 0
    total = 0
    conflicts: list[str] = []
    for item_id in sorted(by_id):
        group = by_id[item_id]
        manual_labels = {item.manual_sentiment for item in group}
        if len(manual_labels) > 1:
            conflicts.append(item_id)
            continue
        total += 1
        if group[0].agreement:
            agreed += 1
    return AgreementBreakdown(
        total=total,
        agreed=agreed,
        rate=(agreed / total) if total else None,
        conflicting_items=tuple(conflicts),
    )


def _check_gate_intersection(
    all_rows: Sequence[SheetRow], eval_sheet: Path
) -> GateIntersection:
    eval_records = _load_records(eval_sheet)
    eval_sentences = {
        _norm_text(_cell_str(rec.get("text_clean") or rec.get("kalimat")))
        for rec in eval_records
    }
    eval_sentences.discard("")

    matched_rows = [row for row in all_rows if _norm_text(row.sentence) in eval_sentences]
    matched_sentences = {_norm_text(row.sentence) for row in matched_rows}
    matched_ids = tuple(sorted({row.item_id for row in matched_rows if row.item_id}))
    return GateIntersection(
        eval_sheet_path=str(eval_sheet),
        eval_total_rows=len(eval_records),
        matched_sentences_total=len(matched_sentences),
        matched_answered_rows=sum(1 for row in matched_rows if row.is_answered),
        matched_blank_rows=sum(1 for row in matched_rows if not row.is_answered),
        matched_overlap_rows=sum(1 for row in matched_rows if row.is_overlap),
        matched_non_overlap_rows=sum(1 for row in matched_rows if not row.is_overlap),
        matched_item_ids=matched_ids,
    )


def _preview(text: str, limit: int = 88) -> str:
    compact = _WHITESPACE.sub(" ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


# ------------------------------------------------------------------ core audit
def audit_sheets(
    sheet_paths: Sequence[Path | str],
    *,
    players_path: Path | str = DEFAULT_PLAYERS,
    corpus_path: Path | str | None = None,
    predictions_path: Path | str | None = None,
    eval_sheet_path: Path | str | None = None,
) -> AuditReport:
    """Run a full read-only audit across one or more external team sheets."""
    if not sheet_paths:
        raise ValueError("at least one label sheet path is required")

    players = load_players(players_path)
    name_to_pid, ambiguous_names = _build_player_name_index(players)

    corpus_index: dict[tuple[str, str], CorpusMatch] = {}
    resolved_corpus_path: str | None = None
    if corpus_path is not None:
        cpath = Path(corpus_path)
        corpus_index = _build_corpus_index(_load_records(cpath))
        resolved_corpus_path = str(cpath)

    prediction_index: dict[tuple[str, str], tuple[str, float | None]] = {}
    resolved_pred_path: str | None = None
    if predictions_path is not None:
        ppath = Path(predictions_path)
        pred_records = _load_records(ppath)
        prediction_index = _build_prediction_index(pred_records)
        resolved_pred_path = str(ppath)
        if not corpus_index:
            corpus_index = _build_corpus_index(pred_records)
            resolved_corpus_path = str(ppath)

    sheet_summaries: list[SheetSummary] = []
    sheets_rows: dict[str, list[SheetRow]] = {}
    all_rows: list[SheetRow] = []
    warnings: list[str] = []

    if ambiguous_names:
        warnings.append(
            f"ambiguous name_canonical in locked sample withheld from automatic mapping: "
            f"{', '.join(sorted(ambiguous_names))}"
        )

    seen_labels: Counter[str] = Counter()
    for raw_path in sheet_paths:
        path = Path(raw_path)
        base_label = path.stem
        seen_labels[base_label] += 1
        label = base_label if seen_labels[base_label] == 1 else f"{base_label}#{seen_labels[base_label]}"
        rows, invalid_cells = read_label_sheet(path, sheet_label=label)
        sheets_rows[label] = rows
        all_rows.extend(rows)

        link_counts = Counter(row.link_label or "blank" for row in rows)
        sentiment_counts = Counter(row.sentiment_label or "blank" for row in rows)
        in_sample_rows = 0
        in_sample_players: set[str] = set()
        out_sample_players: set[str] = set()
        for row in rows:
            if _norm_name(row.player_name) in name_to_pid:
                in_sample_rows += 1
                in_sample_players.add(row.player_name)
            elif row.player_name:
                out_sample_players.add(row.player_name)

        sheet_summaries.append(
            SheetSummary(
                sheet=label,
                path=str(path),
                total_rows=len(rows),
                answered_rows=sum(1 for row in rows if row.is_answered),
                overlap_total=sum(1 for row in rows if row.is_overlap),
                overlap_answered=sum(
                    1 for row in rows if row.is_overlap and row.is_answered
                ),
                non_overlap_total=sum(1 for row in rows if not row.is_overlap),
                non_overlap_answered=sum(
                    1 for row in rows if not row.is_overlap and row.is_answered
                ),
                link_counts=dict(sorted(link_counts.items())),
                sentiment_counts=dict(sorted(sentiment_counts.items())),
                in_locked_sample_rows=in_sample_rows,
                in_locked_sample_players=len(in_sample_players),
                out_of_sample_players=tuple(sorted(out_sample_players)),
                invalid_cells=tuple(invalid_cells),
            )
        )

    overlap_checks = _check_overlap_pairs(sheets_rows)
    for check in overlap_checks:
        if check.possible_copy:
            warnings.append(
                f"overlap L001-L012 between {check.sheet_a} and {check.sheet_b} is "
                f"{check.identical_decisions}/{check.shared_answered} identical "
                f"({check.decision_agreement:.1%}); treat as potential copy, NOT "
                "inter-annotator reliability (Cohen's kappa)."
            )

    mapped_items: list[MappedItem] = []
    unmapped_reasons: Counter[str] = Counter()
    for row in all_rows:
        if not row.is_answered:
            unmapped_reasons["blank_row"] += 1
            continue
        norm_player = _norm_name(row.player_name)
        if norm_player in ambiguous_names:
            unmapped_reasons["ambiguous_player_name"] += 1
            continue
        pid = name_to_pid.get(norm_player)
        if pid is None:
            unmapped_reasons["player_not_in_sample"] += 1
            continue
        if not corpus_index:
            unmapped_reasons["no_corpus_supplied"] += 1
            continue
        match = corpus_index.get((pid, _norm_text(row.sentence)))
        if match is None:
            unmapped_reasons["text_not_in_corpus"] += 1
            continue

        model_sent: str | None = None
        model_score: float | None = None
        agreement: bool | None = None
        if prediction_index:
            pred = prediction_index.get((pid, match.text_id))
            if pred is not None:
                model_sent, model_score = pred
                if row.is_sentiment_scorable:
                    agreement = row.sentiment_label == model_sent

        mapped_items.append(
            MappedItem(
                sheet=row.sheet,
                item_id=row.item_id,
                is_overlap=row.is_overlap,
                player_id=pid,
                player_name=row.player_name,
                text_id=match.text_id,
                unit_type=match.unit_type,
                link_label=row.link_label,
                manual_sentiment=row.sentiment_label,
                model_sentiment=model_sent,
                model_score=model_score,
                agreement=agreement,
                sentence_preview=_preview(row.sentence),
            )
        )

    agreement_all: AgreementBreakdown | None = None
    agreement_overlap: AgreementBreakdown | None = None
    agreement_non_overlap: AgreementBreakdown | None = None
    agreement_unique: AgreementBreakdown | None = None
    if prediction_index:
        agreement_all = _agreement_for(mapped_items)
        agreement_overlap = _agreement_for([m for m in mapped_items if m.is_overlap])
        agreement_non_overlap = _agreement_for(
            [m for m in mapped_items if not m.is_overlap]
        )
        agreement_unique = _unique_item_agreement(mapped_items)
        if agreement_unique.conflicting_items:
            warnings.append(
                "annotator sentiment conflicts on unique mapped item(s): "
                f"{', '.join(agreement_unique.conflicting_items)} "
                "(excluded from unique-item agreement rate)."
            )

    gate_intersection: GateIntersection | None = None
    if eval_sheet_path is not None:
        gate_intersection = _check_gate_intersection(all_rows, Path(eval_sheet_path))

    return AuditReport(
        mapping_method=MAPPING_METHOD,
        players_path=str(players_path),
        corpus_path=resolved_corpus_path,
        predictions_path=resolved_pred_path,
        sheets=tuple(sheet_summaries),
        overlap_checks=tuple(overlap_checks),
        mapped_items=tuple(mapped_items),
        unmapped_reasons=dict(sorted(unmapped_reasons.items())),
        agreement_all_rows=agreement_all,
        agreement_overlap_rows=agreement_overlap,
        agreement_non_overlap_rows=agreement_non_overlap,
        agreement_unique_items=agreement_unique,
        gate_intersection=gate_intersection,
        warnings=tuple(warnings),
    )


# ------------------------------------------------------------------ rendering
def _fmt_breakdown(label: str, breakdown: AgreementBreakdown) -> str:
    if breakdown.total == 0 or breakdown.rate is None:
        return f"  {label:<28} 0/0 (no scorable items)"
    suffix = (
        f" [conflicts excluded: {', '.join(breakdown.conflicting_items)}]"
        if breakdown.conflicting_items
        else ""
    )
    return f"  {label:<28} {breakdown.agreed}/{breakdown.total} ({breakdown.rate:.1%}){suffix}"


def render_report(report: AuditReport) -> str:
    """Format the audit report as plain text for stdout (never written to disk)."""
    lines: list[str] = [
        "External label sheet audit (read-only)",
        f"Mapping method : {report.mapping_method}",
        f"Locked sample  : {report.players_path}",
    ]
    if report.corpus_path:
        lines.append(f"Corpus source  : {report.corpus_path}")
    if report.predictions_path:
        lines.append(f"Predictions    : {report.predictions_path}")
    lines.append("")

    section = 1
    lines.append(
        f"{section}. Sheet coverage (overlap L001-L012 separated from non-overlap L013+)"
    )
    for s in report.sheets:
        lines.append(
            f"  {s.sheet:<16} answered {s.answered_rows}/{s.total_rows} "
            f"(overlap {s.overlap_answered}/{s.overlap_total}, "
            f"non-overlap {s.non_overlap_answered}/{s.non_overlap_total}) | "
            f"in locked sample: {s.in_locked_sample_rows}/{s.total_rows} rows "
            f"({s.in_locked_sample_players} players)"
        )
        lines.append(
            f"    membahas_pemain: {s.link_counts} | sentimen: {s.sentiment_counts}"
        )
        if s.out_of_sample_players:
            lines.append(
                f"    out-of-sample players ({len(s.out_of_sample_players)}): "
                + ", ".join(s.out_of_sample_players)
            )
        if s.invalid_cells:
            lines.append(f"    invalid cells ({len(s.invalid_cells)}):")
            for cell in s.invalid_cells[:10]:
                lines.append(
                    f"      row {cell.row_number} ({cell.item_id}) "
                    f"`{cell.column}` = {cell.value!r}"
                )

    if report.overlap_checks:
        section += 1
        lines.append("")
        lines.append(f"{section}. Overlap consistency check (L001-L012)")
        for check in report.overlap_checks:
            flag = " [POSSIBLE COPY - DO NOT USE FOR KAPPA]" if check.possible_copy else ""
            lines.append(
                f"  {check.sheet_a} vs {check.sheet_b}: "
                f"{check.identical_decisions}/{check.shared_answered} identical "
                f"({check.decision_agreement:.1%}, with aspect "
                f"{check.identical_with_aspect}/{check.shared_answered}){flag}"
            )

    section += 1
    lines.append("")
    lines.append(f"{section}. Corpus mapping summary")
    overlap_mapped = sorted(
        (m for m in report.mapped_items if m.is_overlap),
        key=lambda m: (m.item_id.upper(), m.sheet),
    )
    non_overlap_mapped = sorted(
        (m for m in report.mapped_items if not m.is_overlap),
        key=lambda m: (m.item_id.upper(), m.sheet),
    )
    unique_mapped_ids = {m.item_id.upper() for m in report.mapped_items}
    lines.append(
        f"  Mapped rows: {len(report.mapped_items)} "
        f"(overlap L001-L012: {len(overlap_mapped)}, "
        f"non-overlap L013+: {len(non_overlap_mapped)}, "
        f"unique item_ids: {len(unique_mapped_ids)})"
    )
    if report.unmapped_reasons:
        lines.append(f"  Unmapped breakdown: {report.unmapped_reasons}")

    if report.agreement_all_rows is not None:
        section += 1
        lines.append("")
        lines.append(
            f"{section}. Outside-gate sentiment check (INDICATIVE ONLY - NOT PRD §11 GATE)"
        )
        lines.append(_fmt_breakdown("All mapped scorable rows", report.agreement_all_rows))
        assert report.agreement_overlap_rows is not None
        assert report.agreement_non_overlap_rows is not None
        assert report.agreement_unique_items is not None
        lines.append(
            _fmt_breakdown("Overlap rows (L001-L012)", report.agreement_overlap_rows)
        )
        lines.append(
            _fmt_breakdown(
                "Non-overlap rows (L013+)", report.agreement_non_overlap_rows
            )
        )
        lines.append(
            _fmt_breakdown("Unique item_ids (deduped)", report.agreement_unique_items)
        )

    if report.mapped_items:
        section += 1
        lines.append("")
        lines.append(
            f"{section}. Mapped items detail (separated: overlap vs non-overlap)"
        )
        for group_title, group_items in (
            ("Overlap (L001-L012)", overlap_mapped),
            ("Non-overlap (L013+)", non_overlap_mapped),
        ):
            lines.append(f"  [{group_title}] ({len(group_items)} row(s))")
            if not group_items:
                lines.append("    (none)")
                continue
            for item in group_items:
                if item.model_sentiment is not None:
                    verdict = (
                        "MATCH"
                        if item.agreement is True
                        else "DIFF"
                        if item.agreement is False
                        else "SKIP"
                    )
                    cmp_part = (
                        f" | manual={item.manual_sentiment or '-'} "
                        f"vs model={item.model_sentiment} [{verdict}]"
                    )
                else:
                    cmp_part = (
                        f" | link={item.link_label or '-'} "
                        f"sent={item.manual_sentiment or '-'}"
                    )
                lines.append(
                    f"    {item.item_id} | {item.sheet} | {item.player_id} ({item.player_name}) | "
                    f"{item.text_id}{cmp_part} | {item.sentence_preview}"
                )

    if report.gate_intersection is not None:
        g = report.gate_intersection
        section += 1
        lines.append("")
        lines.append(
            f"{section}. Official gate intersection (read-only check; do not import)"
        )
        lines.append(
            f"  Eval sheet ({g.eval_total_rows} rows): "
            f"{g.matched_sentences_total} matching sentence(s) "
            f"(answered rows: {g.matched_answered_rows}, blank rows: {g.matched_blank_rows}; "
            f"overlap: {g.matched_overlap_rows}, non-overlap: {g.matched_non_overlap_rows})"
        )
        if g.matched_item_ids:
            lines.append(f"  Matched item_ids: {', '.join(g.matched_item_ids)}")

    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in report.warnings:
            lines.append(f"  - {warning}")

    lines.append("")
    lines.append(
        "Note: Read-only audit. External sheets are never written to data/interim/ "
        "or data/processed/, and outside-gate figures are indicative only."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of external team label sheets against the locked "
            "sample, repository corpus, and optional sentiment predictions."
        )
    )
    parser.add_argument(
        "sheets",
        nargs="+",
        type=Path,
        help="One or more external .xlsx or .csv annotator sheets.",
    )
    parser.add_argument(
        "--players",
        type=Path,
        default=DEFAULT_PLAYERS,
        help="Locked player sample parquet/csv (default: data/processed/text_sample.parquet).",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="Optional texts corpus (.parquet or .jsonl) to resolve text_id.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Optional text_analysis (.parquet, .jsonl, or .csv) for indicative sentiment check.",
    )
    parser.add_argument(
        "--eval-sheet",
        type=Path,
        default=None,
        help="Optional official eval_linking_sentiment.csv to measure sentence intersection.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON to stdout instead of plain text.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(name)s: %(message)s")
    try:
        report = audit_sheets(
            args.sheets,
            players_path=args.players,
            corpus_path=args.corpus,
            predictions_path=args.predictions,
            eval_sheet_path=args.eval_sheet,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"label audit error: {exc}") from exc

    if args.as_json:
        sys.stdout.write(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(render_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - invoked via CLI
    raise SystemExit(main())
