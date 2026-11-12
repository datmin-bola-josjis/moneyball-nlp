# Pemain Undervalued — Sinyal Kualitas dari Teks (Premier League 2025/26)

Tugas besar Data Mining, Semester 5. Empat orang, satu minggu.

**Pertanyaan riset:** apakah sinyal kualitas dari teks (sentiment per aspek) bisa mengidentifikasi pemain berharga murah yang performanya terbukti di angka?

Teks adalah metode inti. Angka berperan sebagai harga dan validator. Populasi pemain diambil dari data terstruktur, bukan dari teks, supaya pemain yang jarang dibicarakan tidak terlewat.

> **Rumusan yang dipakai di seluruh repo:** teks mengindikasikan kualitas, angka memvalidasi performa, harga menunjukkan peluang.

## Mulai

```bash
git clone https://github.com/datmin-bola-josjis/moneyball-nlp.git
cd moneyball-nlp
make setup                   # install dependencies
cp .env.example .env         # isi kredensial Reddit/YouTube
make config                  # validasi config/config.yaml
```

**Baru bergabung?** Baca [`docs/GAMBARAN-BESAR.md`](docs/GAMBARAN-BESAR.md) dulu (10 menit), lalu [`CONTRIBUTING.md`](CONTRIBUTING.md) untuk alur branch dan commit.

## Status

Draf Hari 0. Scaffold repo sudah siap, **belum ada kode pipeline**. Yang harus dikunci di Hari 1:

1. Skema tabel `players` dan `texts` ([`docs/PRD.md`](docs/PRD.md) §8)
2. Daftar sampel 60–80 pemain, disimpan sebagai file dan dikunci
3. Keputusan akses Reddit (jalan atau pivot ke YouTube)
4. Verifikasi 20 nama subreddit klub lewat API ber-auth

## Dokumen

| File | Isi |
|---|---|
| [`docs/GAMBARAN-BESAR.md`](docs/GAMBARAN-BESAR.md) | **Baca ini dulu.** Penjelasan singkat proyek ini ngapain, dan tugas tiap peran |
| [`docs/PRD.md`](docs/PRD.md) | Spesifikasi lengkap: scope, sumber data, pipeline A–F, skema dataset, definisi, metrik, risiko, etika |
| [`docs/PLAN-1WEEK.md`](docs/PLAN-1WEEK.md) | Pembagian peran 4 orang, jadwal 7 hari, apa yang dipangkas dari PRD penuh, struktur laporan CRISP-DM |
| [`docs/decisions.md`](docs/decisions.md) | Catatan setiap perubahan ambang dan keputusan teknis, beserta alasannya |
| [`config/config.yaml`](config/config.yaml) | Liga, musim, whitelist sumber, ambang, kuota — satu-satunya tempat menyimpan parameter |
| [`AGENTS.md`](AGENTS.md) | Aturan wajib untuk agent AI dan anggota tim |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup, alur branch, format commit |

## Struktur

```text
config/config.yaml        parameter proyek (liga, whitelist, ambang, kuota)
docs/                     PRD, rencana, log keputusan
src/population/           Tahap A — populasi pemain dan sampel terkunci
src/scrape/               Tahap B — retrieval teks (Reddit, YouTube, artikel)
src/link/                 Tahap C — entity linking per kalimat
src/nlp/                  Tahap D — sentiment dan aspek
src/score/                Tahap E — skor kualitas, validasi angka, kandidat
src/viz/                  Tahap F — visualisasi dan tabel output
data/raw/                 data mentah, tidak pernah ditimpa, tidak di-commit
data/processed/           data bersih (text_sample.parquet = daftar sampel terkunci)
reports/figures/          gambar hasil `make viz`
tests/                    test minimal: alias matching, filter tanggal, skema
```

Satu perintah dari data mentah ke output: `make pipeline`.

## Tiga keputusan yang masih menggantung

1. **Bentuk akhir yang dinilai** — laporan tertulis, presentasi, atau demo dashboard? Kalau laporan saja, dashboard dibuang dan waktunya dipakai untuk evaluasi yang lebih kuat.
2. **Porsi kolom numerik** yang diizinkan dosen agar dataset tetap "dominan string".
3. **Akses X/Twitter** — default dilewati.

## Prinsip yang tidak boleh dilanggar

- Populasi dari data terstruktur, teks hanya untuk penilaian.
- Scraping player-centric, per pemain, dengan batas tanggal.
- Pecah per kalimat sebelum entity linking; jangan labeli satu thread ke satu pemain.
- Pemain dengan teks sedikit diberi label "bukti tidak cukup", bukan dinilai paksa.
- Angka tidak boleh dipakai untuk membentuk skor kualitas.

Daftar lengkap ada di [`AGENTS.md`](AGENTS.md).

## Data dan etika

Hanya data publik. Tidak menembus paywall. Username penulis komentar tidak disimpan. Data mentah tidak diredistribusi — yang dibagikan hanya agregat dan kode. Lihat [`docs/PRD.md`](docs/PRD.md) §13.

