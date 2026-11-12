# Panduan Kontribusi

Empat orang, satu minggu. Aturan di sini menjaga agar kerja paralel tidak saling menimpa.

Baca [`AGENTS.md`](AGENTS.md) lebih dulu — di situ aturan proyek yang tidak boleh dilanggar (populasi dari data terstruktur, skor kualitas hanya dari teks, dan seterusnya).

## Setup pertama kali

```bash
git clone https://github.com/datmin-bola-josjis/moneyball-nlp.git
cd moneyball-nlp
make setup                      # install dependencies
cp .env.example .env            # lalu isi kredensial Reddit/YouTube
make config                     # cek config/config.yaml valid
```

`.env` tidak pernah di-commit. Kalau kredensial belum ada, Tahap B tidak bisa jalan — lapor ke tim, jangan mencari jalan memutar.

## Alur kerja

1. **Selalu mulai dari `main` yang terbaru.**

   ```bash
   git switch main && git pull --rebase
   git switch -c feat/reddit-scraper
   ```

2. **Satu branch, satu pekerjaan.** Penamaan:

   | Prefix | Untuk | Contoh |
   |---|---|---|
   | `feat/` | fitur atau tahap baru | `feat/youtube-scraper` |
   | `fix/` | perbaikan bug | `fix/date-filter-timezone` |
   | `docs/` | dokumen saja | `docs/kunci-skema-hari1` |
   | `data/` | skrip pengolahan data | `data/alias-matching` |

3. **Commit kecil dan bermakna.** Satu commit = satu perubahan logis. Jangan campur refactor dengan fitur.

4. **Buka Pull Request.** Isi template PR. Reviewer minimal satu orang dari tim.

5. **Yang merge ke `main` hanya D** (pemegang struktur repo, lihat `docs/PLAN-1WEEK.md` §2). Tidak ada force push ke `main`.

## Format commit

Conventional Commits, bahasa Inggris, baris judul ≤ 72 karakter, mood imperatif.

```text
feat(scrape): add reddit player-centric query builder
fix(link): keep sentences with club context when name is ambiguous
docs(prd): lock table schema for players and texts
data(population): derive name aliases from roster
test(nlp): add negative test for aspect keyword collision
chore(deps): pin pandas to 2.x
```

Scope mengikuti tahap pipeline: `population`, `scrape`, `link`, `nlp`, `score`, `viz`, `config`, `docs`.

Yang **tidak** boleh masuk commit: kredensial, `.env`, data mentah, file `.parquet`, notebook dengan output besar.

## Perubahan yang butuh persetujuan tim

Buka issue atau bicarakan dulu sebelum mengerjakan:

- Mengubah nama kolom pada skema tabel yang sudah dikunci (`docs/PRD.md` §8)
- Mengubah ambang persentil di `config/config.yaml` — wajib dicatat di `docs/decisions.md`
- Menambah dependensi
- Menambah anggota populasi di luar data terstruktur

## Data dan file yang tidak di-commit

| Path | Alasan |
|---|---|
| `data/raw/` | Data mentah tidak untuk diredistribusi (`docs/PRD.md` §13) |
| `data/interim/` | Hasil antara, bisa dibuat ulang |
| `data/processed/*.parquet` | Kecuali `text_sample.parquet` — daftar sampel terkunci harus tetap teraudit |
| `.env` | Kredensial |
| `HANDOFF.md` | State sesi agent, spesifik mesin |
| `reports/figures/*.png` | Gambar dihasilkan ulang oleh `make viz` |

## Bahasa

Dokumen dan komentar diskusi: **Indonesia**. Kode, nama variabel, komentar kode, pesan commit, dan pesan error: **Inggris**.

## Sebelum menyatakan selesai

Jalankan `make check` (validasi config + test), lalu periksa checklist di [`AGENTS.md`](AGENTS.md) bagian "Checklist sebelum menyatakan tugas selesai".
