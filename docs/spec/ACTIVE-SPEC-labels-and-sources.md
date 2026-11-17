# ACTIVE SPEC: Gate Pelabelan + Transkrip YouTube + Artikel

> **Status:** disetujui user 2026-11-17. Spec terpisah dari `ACTIVE-SPEC.md`
> (Obsidian Terminal) supaya pekerjaan Role D tidak tertimpa.

## 0. Objective

Tiga slice, semuanya menambah **bukti**, bukan mengubah keputusan metodologi:

- **S1 — Alat bantu gate pelabelan.** Tim masih harus melabeli 300 baris manual
  (`review_relevance.csv` 100, `review_relevance_youtube.csv` 100,
  `eval_linking_sentiment.csv` 100). Yang hilang bukan labelnya, melainkan cara
  tahu *apa yang belum diisi* dan *apakah isian sudah sah* sebelum skor dihitung.
- **S2 — Transkrip YouTube.** `include_transcript: true` sudah ada di config
  sejak awal tetapi tidak pernah diimplementasikan, sehingga config menjanjikan
  sesuatu yang tidak dilakukan kode.
- **S3 — Artikel (bonus).** PRD §12 Tahap B menyebut artikel sebagai sumber
  pelengkap; sekarang `text_sources.article.enabled: false` dan tidak ada kode.

## 1. Honest-claims boundary

- S1 **tidak mengisi label apa pun**. Label adalah penilaian manusia atas teks
  berbahasa Inggris; label buatan model bukan bukti evaluasi dan akan merusak
  Cohen's κ (AGENTS.md aturan 9 & 16).
- S2/S3 **tidak menambah anggota populasi**. Populasi tetap
  `text_sample.parquet` (aturan 1 & 14).
- S2/S3 tidak menjanjikan lolos gate relevansi ≥ 85%. Gate itu baru terukur
  setelah 100 teks dilabeli manusia (S1).
- Transkrip adalah teks **orang lain berbicara**, bukan komentar penonton. Ia
  tetap sinyal kualitas, tetapi keterbatasan ini wajib disebut di laporan.

## 2. Slices

### S1 — `src/scrape/labels.py` + `make labels-status`

- Masukan: tiga CSV di `data/interim/`. Keluaran: ringkasan progres per lembar
  (terisi / total, per anotator untuk `eval_linking_sentiment.csv`) dan daftar
  masalah format.
- **Oracle deterministik:** fungsi murni atas isi CSV, diuji tanpa jaringan.
- Perilaku wajib:
  - CSV tidak ada → dilaporkan `missing`, bukan crash.
  - Nilai label tak dikenal (`"mungkin"`) → dihitung sebagai *belum terisi* dan
    dilaporkan sebagai format salah; tidak pernah ditebak menjadi `True`.
  - Nilai sah: `y/n/yes/no/1/0/true/false/relevan/tidak` (sama dengan
    `src/scrape/relevance._parse_label`) dan `positive/neutral/negative` untuk
    sentimen manual (sama dengan `src/nlp/analyze.score_eval_sheet`).
  - Exit code `1` bila ada baris yang formatnya salah, supaya skrip bisa dipakai
    di gate; `0` bila bersih (termasuk saat masih 0 terisi).

### S2 — Transkrip di `src/scrape/youtube.py`

- **Koreksi terhadap draf awal spec ini.** Draf pertama mengklaim PRD §8
  mengizinkan `transcript_segment`; itu **salah** — PRD §8 hanya mengunci
  `comment`/`sentence`, dan `src/nlp/analyze.py` memilih `unit_type == "sentence"`
  saja. Transkrip karena itu ditulis sebagai `unit_type="sentence"` (dipecah per
  kalimat), sehingga benar-benar sampai ke Stage D. Rinciannya di
  `docs/decisions.md` 2026-11-14.
- Segmen dipotong dari transkrip utuh dengan jendela kata (default 60, tumpang
  tindih 0) agar satu segmen cukup panjang untuk dinilai sentimennya.
- Filter sama seperti komentar: `min_words`, bahasa Inggris, dalam musim,
  dedupe hash, dan `matched_alias` dari `AliasIndex`.
- Kegagalan transkrip (dimatikan uploader, tak ada transkrip) **bukan** error
  fatal: dihitung ke `counters` (`transcript_disabled`, `transcript_missing`) dan
  tercatat di `summary.json`.
- `include_transcript: false` → tidak ada satu pun segmen, dan summary
  menyatakan alasannya.

### S3 — `src/scrape/article.py` + `make scrape-articles`

- `text_sources.article.enabled` tetap `false` secara default; target Makefile
  hanya melakukan sesuatu bila diaktifkan (aturan: config satu-satunya saklar).
- URL dari halaman tag/RSS situs whitelist, isi diekstrak `trafilatura`.
- Artikel masuk hanya bila nama pemain ada di judul **atau** ≥
  `min_name_mentions` (config, default 3) di isi — persis PRD §12.
- Tidak menembus paywall: domain berbayar dilewati bila `respect_paywall: true`
  dan tidak ada akses; kegagalan dicatat, bukan diulang paksa.
- `source="article"`, `unit_type="sentence"` (koreksi yang sama seperti transkrip);
  `channel` memuat domain penerbit (kolom yang sudah ada — tidak menambah kolom).
- `run()` menolak berjalan bila `src/link/resolve.py` belum punya cabang
  `article` (`_require_downstream_filter`), supaya aturan 17 tidak bisa dilewati
  hanya karena modul ini aktif lebih dulu.

## 3. Oracles

| Slice | Perintah | Lulus bila |
|---|---|---|
| S1 | `make check` | test unit hijau; `make labels-status` pada CSV asli melaporkan `0/100` untuk ketiga lembar dan exit `0` |
| S1 | `make labels-status` pada CSV berisi label ngawur | exit `1`, menyebut kolom & baris |
| S2 | `make check` | test dengan klien transkrip palsu hijau; tidak ada test yang memanggil jaringan |
| S3 | `make check` | test dengan fetcher palsu hijau; `min_name_mentions` diuji di batas (2 → tolak, 3 → terima) |
| semua | `make check` | `make config` PASS dan pytest hijau |

## 4. Out of scope

- Mengisi label (itu pekerjaan manusia).
- Mengaktifkan artikel di config (keputusan tim; butuh catatan
  `docs/decisions.md`).
- Menjalankan scrape penuh ke jaringan pada slice ini — bukti jaringan dilaporkan
  terpisah dan apa adanya bila dijalankan.
