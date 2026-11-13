"""Cross-source dedupe between Reddit and YouTube texts (Stage C, PRD §7).

The scrapers already remove duplicates *within* one source with
`text_clean_hash`. This module compares the two sources against each other: the
same comment appearing on Reddit and under a video is one piece of evidence
counted twice, and counting it twice doubles its weight in the sentiment average.

Scope is deliberately narrow, for reasons measured on the real files:

- **comments are compared with comments, sentences with sentences.** A comment
  and its own sentence share a hash by construction (281 such pairs in the pilot
  Reddit file, 556 in the YouTube run). A plain `drop_duplicates` on the hash
  would delete the sentence-level unit the sentiment stage runs on.
- **the key is `(player_id, text_clean_hash)`, not the hash alone.** One comment
  can legitimately mention two players (84 such hashes in the pilot Reddit
  file). Collapsing those would break correct entity links.
- **nothing is removed inside one source.** That already happened upstream, and
  re-doing it here would hide whether the scraper worked.

Survivor rule: the Reddit row is kept and the YouTube copy is dropped. Reddit is
the primary source in PRD §7 and its rows carry `subreddit`, which the retrieval
report groups by. The text is identical, so the choice cannot change sentiment.

The output is a new file. Inputs are only read, so a wrong run costs nothing but
a delete (AGENTS.md rule 5).
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from src.config import ROOT

log = logging.getLogger("dedupe")

INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "dedupe.md"
OUTPUT = PROCESSED / "texts_deduped.parquet"

SOURCES = ("reddit", "youtube")
# Reddit's 15 columns first, then the two YouTube-only ones. A fixed order keeps
# the parquet readable by both pandas and a human without reordering later.
COLUMNS = [
    "text_id",
    "player_id",
    "source",
    "unit_type",
    "text_raw",
    "text_clean",
    "text_clean_hash",
    "language",
    "created_at",
    "url",
    "thread_id",
    "subreddit",
    "engagement",
    "matched_alias",
    "parent_text_id",
    "channel",
    "video_id",
]
COMMANDS = {"reddit": "make scrape-arctic", "youtube": "make scrape-youtube"}


# ------------------------------------------------------------------- reading
def texts_path(source: str, tag: str, interim: Path | None = None) -> Path:
    """`texts_<source>_<tag>.jsonl` in `data/interim`.

    The tag is explicit on purpose. Picking the newest file would silently read
    `partial26` while waiting for `full`, and the resulting number would describe
    a different sample than the report claims.
    """
    base = Path(interim) if interim is not None else INTERIM
    return base / f"texts_{source}_{tag}.jsonl"


def read_texts(source: str, tag: str, interim: Path | None = None) -> tuple[list[dict], Path]:
    path = texts_path(source, tag, interim)
    if not path.exists():
        raise SystemExit(
            f"no {source} texts at {path}. Run `{COMMANDS[source]}` first, or pass "
            f"the tag of a finished run (--{source}-tag)."
        )
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    log.info("reading %s (%d rows)", path.name, len(rows))
    return rows, path


# ------------------------------------------------------------------- dedupe
def _key(row: dict) -> tuple[str, str]:
    """`(player_id, text_clean_hash)`, with a fallback that can never collide.

    A row without a hash cannot be compared with anything. Falling back to the
    empty string would collapse every such row into one duplicate, so the unique
    `text_id` is used instead: the row is kept, which is the safe direction.
    """
    digest = str(row.get("text_clean_hash") or "").strip()
    if not digest:
        return ("", str(row.get("text_id") or ""))
    return (str(row.get("player_id") or ""), digest)


def _diagnostics(rows: list[dict]) -> dict:
    """Count the two patterns that make a naive dedupe destructive.

    These are reported, not acted on: they explain why the scope is what it is,
    and they make a regression visible if a future edit widens it.
    """
    hashes = Counter(str(r.get("text_clean_hash") or "") for r in rows)
    players: dict[str, set[str]] = defaultdict(set)
    types: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        digest = str(row.get("text_clean_hash") or "")
        if not digest:
            continue
        players[digest].add(str(row.get("player_id") or ""))
        types[digest].add(str(row.get("unit_type") or ""))
    # Same text, same player, same unit: the one duplicate a single-source
    # scraper is supposed to have removed. Reported so the claim "the scraper
    # already did this" is checked rather than assumed.
    same = Counter(
        (str(r.get("player_id") or ""), str(r.get("unit_type") or ""), str(r.get("text_clean_hash") or ""))
        for r in rows
        if r.get("text_clean_hash")
    )
    return {
        "rows": len(rows),
        "unique_hashes": len([h for h in hashes if h]),
        "repeated_hashes": sum(1 for h, n in hashes.items() if h and n > 1),
        "hashes_across_players": sum(1 for p in players.values() if len(p) > 1),
        "hashes_comment_and_sentence": sum(1 for t in types.values() if len(t) > 1),
        "within_player_repeats": sum(1 for n in same.values() if n > 1),
    }


def merge(reddit_rows: list[dict], youtube_rows: list[dict]) -> tuple[list[dict], dict]:
    """Return the merged rows plus the counts the report needs.

    Three passes, in order:

    1. comments whose `(player_id, hash)` already exists on Reddit are dropped
       from YouTube;
    2. the sentences of those comments are dropped with them - their parent
       evidence is a duplicate, so keeping the children would double-count at
       the level the sentiment stage actually runs on;
    3. YouTube sentences that match a surviving Reddit sentence under the same
       player are dropped. This catches the same line quoted in two different
       comments, which pass 1 cannot see.
    """
    reddit_comments = [r for r in reddit_rows if r.get("unit_type") == "comment"]
    youtube_comments = [r for r in youtube_rows if r.get("unit_type") == "comment"]

    reddit_comment_keys = {_key(r) for r in reddit_comments}
    duplicate_comments = [r for r in youtube_comments if _key(r) in reddit_comment_keys]
    dropped_comment_ids = {str(r.get("text_id")) for r in duplicate_comments}

    orphaned = [
        r
        for r in youtube_rows
        if r.get("unit_type") == "sentence"
        and str(r.get("parent_text_id")) in dropped_comment_ids
    ]
    youtube_after_comments = [
        r
        for r in youtube_rows
        if str(r.get("text_id")) not in dropped_comment_ids
        and str(r.get("parent_text_id")) not in dropped_comment_ids
    ]

    reddit_sentence_keys = {_key(r) for r in reddit_rows if r.get("unit_type") == "sentence"}
    duplicate_sentences = [
        r
        for r in youtube_after_comments
        if r.get("unit_type") == "sentence" and _key(r) in reddit_sentence_keys
    ]
    dropped_sentence_ids = {str(r.get("text_id")) for r in duplicate_sentences}
    youtube_kept = [
        r for r in youtube_after_comments if str(r.get("text_id")) not in dropped_sentence_ids
    ]

    rows = list(reddit_rows) + youtube_kept
    affected: Counter[str] = Counter()
    for row in duplicate_comments + duplicate_sentences:
        affected[str(row.get("player_id") or "")] += 1

    stats = {
        "inputs": {
            "reddit": {
                "rows": len(reddit_rows),
                "comments": len(reddit_comments),
                "sentences": len(reddit_rows) - len(reddit_comments),
            },
            "youtube": {
                "rows": len(youtube_rows),
                "comments": len(youtube_comments),
                "sentences": len(youtube_rows) - len(youtube_comments),
            },
        },
        "dropped": {
            "comments": len(duplicate_comments),
            "sentences_same_text": len(duplicate_sentences),
            "sentences_parent_dropped": len(orphaned),
        },
        "kept": {
            "reddit": len(reddit_rows),
            "youtube": len(youtube_kept),
            "total": len(rows),
        },
        "affected": dict(affected),
        "examples": duplicate_comments[:5],
        "diagnostics": {
            "reddit": _diagnostics(reddit_rows),
            "youtube": _diagnostics(youtube_rows),
        },
    }
    return rows, stats


# ------------------------------------------------------------------- output
def write_output(rows: list[dict], path: Path | None = None) -> Path:
    """Write the merged rows as parquet, in the fixed column order.

    Parquet matches the `data/processed/*.parquet` convention in PLAN §7. Columns
    a source does not have (`channel`, `video_id`) stay null instead of being
    filled with `""`, so "not applicable" is distinguishable from "empty".
    """
    target = Path(path) if path is not None else OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    # A schema change in a handoff file must be visible, not silently trimmed:
    # a new column from person B would otherwise disappear without a word.
    seen = {key for row in rows for key in row}
    unknown = sorted(seen - set(COLUMNS))
    if unknown:
        log.warning(
            "dropping %d column(s) not in the schema: %s", len(unknown), ", ".join(unknown)
        )
    frame = pd.DataFrame(rows).reindex(columns=COLUMNS)
    frame.to_parquet(target, index=False)
    log.info("wrote %d rows -> %s", len(frame), target)
    return target


def write_report(
    stats: dict,
    reddit_name: str,
    youtube_name: str,
    path: Path | None = None,
) -> Path:
    target = Path(path) if path is not None else REPORT
    dropped = stats["dropped"]
    inputs = stats["inputs"]
    diagnostics = stats["diagnostics"]

    lines = [
        "# Dedupe silang Reddit × YouTube (Tahap C)",
        "",
        "Laporan ini dibuat oleh `src/link/dedupe.py`. Angka di bawah hanya berlaku",
        "untuk dua file masukan yang disebut di sini, bukan untuk run lain.",
        "",
        "## Masukan",
        "",
        "| Sumber | File | Baris | Komentar | Kalimat |",
        "|---|---|---|---|---|",
        f"| Reddit | `{reddit_name}` | {inputs['reddit']['rows']} | "
        f"{inputs['reddit']['comments']} | {inputs['reddit']['sentences']} |",
        f"| YouTube | `{youtube_name}` | {inputs['youtube']['rows']} | "
        f"{inputs['youtube']['comments']} | {inputs['youtube']['sentences']} |",
        "",
        "## Aturan yang dipakai",
        "",
        "- Duplikat = teks dengan `text_clean_hash` sama **untuk pemain yang sama**.",
        "  Satu komentar yang menyebut dua pemain tetap dihitung dua kali, karena",
        "  itu dua tautan entitas yang benar, bukan duplikat.",
        "- Komentar dibandingkan dengan komentar, kalimat dengan kalimat. Komentar",
        "  dan kalimatnya sendiri memang berbagi hash; menyamakan keduanya akan",
        "  menghapus unit yang dipakai analisis sentimen.",
        "- Hanya antar sumber. Duplikat **komentar** di dalam satu sumber sudah",
        "  dibuang scraper lewat `text_clean_hash`. Kalimat identik yang muncul di",
        "  dua komentar berbeda tidak tertangani di sini; jumlahnya dilaporkan di",
        "  bawah, bukan dibuang diam-diam.",
        "- Bila duplikat ditemukan, baris **Reddit** dipertahankan dan salinan",
        "  YouTube dibuang. Teksnya identik, jadi pilihan ini tidak mengubah",
        "  sentimen; Reddit dipilih karena sumber utamanya (PRD §7).",
        "",
        "## Hasil",
        "",
        "| Yang dibuang | Jumlah |",
        "|---|---|",
        f"| Komentar YouTube yang teksnya sama dengan Reddit | {dropped['comments']} |",
        f"| Kalimat YouTube yang teksnya sama dengan kalimat Reddit | "
        f"{dropped['sentences_same_text']} |",
        f"| Kalimat YouTube yang komentar induknya dibuang | "
        f"{dropped['sentences_parent_dropped']} |",
        "",
        "| Yang dipertahankan | Baris |",
        "|---|---|",
        f"| Reddit | {stats['kept']['reddit']} |",
        f"| YouTube | {stats['kept']['youtube']} |",
        f"| **Total** | **{stats['kept']['total']}** |",
        "",
    ]

    total_dropped = sum(dropped.values())
    if total_dropped == 0:
        lines += [
            "**Tidak ada duplikat silang yang ditemukan.** Ini temuan, bukan",
            "kegagalan: komentar Reddit dan komentar YouTube hampir tidak pernah",
            "identik kata per kata, jadi nol adalah hasil yang diharapkan pada",
            "korpus ini. Nilainya ada pada buktinya — bukan pada jumlah yang dibuang.",
            "",
        ]

    lines += [
        "## Mengapa cakupannya dibatasi",
        "",
        "Angka berikut dihitung dari masukan dan **tidak** dipakai untuk membuang",
        "apa pun. Fungsinya menunjukkan bahwa dedupe naif akan merusak data:",
        "",
        "| Pola | Reddit | YouTube |",
        "|---|---|---|",
        f"| Baris | {diagnostics['reddit']['rows']} | {diagnostics['youtube']['rows']} |",
        f"| Hash unik | {diagnostics['reddit']['unique_hashes']} | "
        f"{diagnostics['youtube']['unique_hashes']} |",
        f"| Hash dipakai lebih dari sekali | {diagnostics['reddit']['repeated_hashes']} | "
        f"{diagnostics['youtube']['repeated_hashes']} |",
        f"| Hash dipakai lebih dari satu pemain | "
        f"{diagnostics['reddit']['hashes_across_players']} | "
        f"{diagnostics['youtube']['hashes_across_players']} |",
        f"| Hash dipakai komentar **dan** kalimatnya | "
        f"{diagnostics['reddit']['hashes_comment_and_sentence']} | "
        f"{diagnostics['youtube']['hashes_comment_and_sentence']} |",
        f"| Teks sama untuk pemain yang sama (dalam satu sumber) | "
        f"{diagnostics['reddit']['within_player_repeats']} | "
        f"{diagnostics['youtube']['within_player_repeats']} |",
        "",
        "`drop_duplicates('text_clean_hash')` akan menghapus semua baris pada dua",
        "baris tengah tabel itu — kalimat yang sah dan tautan pemain yang benar.",
        "",
        "Baris terakhir adalah duplikat yang seharusnya sudah dibuang scraper. Untuk",
        "**komentar** memang sudah nol. Yang tersisa adalah **kalimat** yang sama di",
        "dua komentar berbeda pada satu pemain: dua orang mengutip kalimat yang sama,",
        "atau teks berita yang diposting ulang. Dedupe ini tidak menyentuhnya karena",
        "cakupannya hanya antar sumber; kalau D ingin bobot sentimen tidak dihitung",
        "dua kali, saring di tahap agregasi per pemain.",
        "",
    ]

    affected = stats["affected"]
    if affected:
        lines += ["## Pemain terdampak", "", "| player_id | Baris dibuang |", "|---|---|"]
        for player_id, count in sorted(affected.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{player_id}` | {count} |")
        lines.append("")

    examples = stats["examples"]
    if examples:
        lines += ["## Contoh teks yang dibuang", ""]
        for row in examples:
            snippet = " ".join(str(row.get("text_clean") or "").split())[:200]
            lines.append(f"- `{row.get('player_id')}`: {snippet}")
        lines.append("")

    lines += [
        "## Yang tidak diubah",
        "",
        "- File masukan hanya dibaca, tidak pernah ditimpa (aturan 5).",
        "- Duplikat komentar di dalam satu sumber tidak disentuh; itu tugas scraper.",
        "- Baris kalimat yang komentar induknya bertahan tetap ada.",
        "",
        "## Perintah",
        "",
        "```bash",
        "make dedupe                              # default: tag full untuk kedua sumber",
        "make dedupe REDDIT_TAG=partial26         # uji coba pada data pilot",
        "```",
        "",
        "Keluaran: `data/processed/texts_deduped.parquet`.",
    ]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("report -> %s", target)
    return target


# ---------------------------------------------------------------------- run
def run(
    reddit_tag: str = "full",
    youtube_tag: str = "full",
    interim: Path | None = None,
    out: Path | None = None,
    report: Path | None = None,
) -> tuple[Path, Path, dict]:
    reddit_rows, reddit_path = read_texts("reddit", reddit_tag, interim)
    youtube_rows, youtube_path = read_texts("youtube", youtube_tag, interim)

    rows, stats = merge(reddit_rows, youtube_rows)
    output = write_output(rows, out)
    target = write_report(stats, reddit_path.name, youtube_path.name, report)
    log.info(
        "dropped %d comments / %d sentences, kept %d rows",
        stats["dropped"]["comments"],
        stats["dropped"]["sentences_same_text"] + stats["dropped"]["sentences_parent_dropped"],
        stats["kept"]["total"],
    )
    return output, target, stats


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Stage C: drop texts that appear in both Reddit and YouTube"
    )
    parser.add_argument(
        "--reddit-tag",
        default="full",
        help="Reddit run tag (default: full, the canonical handoff)",
    )
    parser.add_argument(
        "--youtube-tag",
        default="full",
        help="YouTube run tag (default: full, the canonical handoff)",
    )
    parser.add_argument("--out", help="output parquet (default data/processed/texts_deduped.parquet)")
    parser.add_argument("--report", help="output report (default reports/dedupe.md)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    run(
        reddit_tag=args.reddit_tag,
        youtube_tag=args.youtube_tag,
        out=Path(args.out) if args.out else None,
        report=Path(args.report) if args.report else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
