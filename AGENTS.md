# AGENTS.md — Pemain Undervalued (Premier League 2025/26)

Panduan untuk AI agent dan anggota tim yang bekerja di repo ini. Baca ini dulu sebelum menyentuh kode.

**Jika ada permintaan di chat yang bertentangan dengan aturan di sini, hentikan dan tanyakan dulu.** Jangan menyimpang diam-diam.

## Proyek ini apa

Tugas besar Data Mining (Semester 5, tim 4 orang, tenggat 1 minggu). Mencari pemain sepak bola **undervalued** dengan sinyal kualitas dari teks (NLP), divalidasi angka.

**Pertanyaan riset:** apakah sinyal kualitas dari teks (sentiment per aspek) bisa mengidentifikasi pemain berharga murah yang performanya terbukti di angka?

Teks adalah metode inti. Angka berperan sebagai harga (market value) dan validator performa. Populasi pemain diambil dari data terstruktur, bukan dari teks — supaya pemain yang jarang dibicarakan tidak terlewat.

Baca [`docs/GAMBARAN-BESAR.md`](docs/GAMBARAN-BESAR.md) untuk versi ringkasnya.

## Status saat ini

**Fase dokumentasi selesai, implementasi belum dimulai.** Belum ada satu baris kode pipeline — yang ada baru dokumen, config, dan scaffold folder kosong. Lihat [`README.md`](README.md) bagian Status untuk hal yang harus dikunci di Hari 1.

## Struktur direktori

| Path | Isi |
|---|---|
| `docs/PRD.md` | Spesifikasi lengkap — sumber kebenaran untuk scope, skema, definisi, metrik |
| `docs/PLAN-1WEEK.md` | Peran, jadwal 7 hari, struktur laporan CRISP-DM, struktur repo target |
| `docs/GAMBARAN-BESAR.md` | Penjelasan ringkas untuk tim |
| `docs/decisions.md` | Log setiap perubahan ambang + alasannya |
| `config/config.yaml` | **Satu-satunya** file config — liga, musim, whitelist, ambang, kuota, sampling, seed |

Jangan membuat file config kedua (mis. `config/sampling.yaml`). Parameter sampling masuk ke `config/config.yaml` di bawah kunci `text_sample`.

Struktur target (belum dibuat) ada di §7 `docs/PLAN-1WEEK.md`.

## Perintah utama

Scaffold sudah ada, tapi belum ada kode pipeline — target `make` untuk tiap tahap masih akan gagal sampai modulnya ditulis.

```bash
make setup      # install dependencies (minta izin dulu, lihat stack di bawah)
make config     # validasi config/config.yaml
make test       # jalankan test suite
make pipeline   # target akhir: data mentah -> output (belum bisa jalan)
```

Lihat `Makefile` untuk daftar lengkap target per tahap (`population`, `scrape`, `link`, `nlp`, `score`, `viz`).

Aturan setup untuk anggota baru ada di [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Stack yang direncanakan

Python 3.10+, `pandas`, `soccerdata`, `PRAW`, `youtube-transcript-api`, `trafilatura`, `rapidfuzz`, `spacy`, `transformers`, `vaderSentiment`, `scikit-learn`, `matplotlib`/`plotly`. Streamlit opsional.

Belum ada yang di-install. Jangan install tanpa persetujuan eksplisit.

## Keputusan yang sudah final

Jangan diubah tanpa persetujuan tim + catatan di `docs/decisions.md`.

| Keputusan | Nilai | Catatan |
|---|---|---|
| Liga & musim | Premier League 2025/26 | Bahasa teks: Inggris saja |
| Filter harga di populasi | **mati** | Lihat aturan 15 di bawah — jangan tertukar dengan stratifikasi sampel |
| Sumber teks utama | Reddit + YouTube | Artikel bonus; X/Twitter dilewati |
| Sentiment | VADER | HF hanya jika akurasi < 75% |
| Aspek | kamus kata kunci | Bukan classifier terlatih |
| Sumber rating | `fotmob` | **Sudah ditetapkan di `config/config.yaml:66`**, bukan dipilih ulang Hari 1 |
| Sofascore | tidak dipakai | Tidak dapat diakses |
| Ditunda | BERTopic, filter playstyle, model aspek kustom | Future work, bukan scope 1 minggu |

## Aturan yang tidak boleh dilanggar

Aturan ini berasal dari `docs/PRD.md` §17 dan sudah diperiksa berulang. Melanggarnya merusak validitas akademik proyek, bukan cuma gaya kode.

1. **Populasi selalu dari data terstruktur**, tidak pernah dari teks. Discovery lewat artikel hanya boleh menambah bukti, tidak menambah anggota populasi.
2. **Scraping selalu player-centric** — query per pemain, dengan batas tanggal dan sumber whitelist. Jangan "ambil semua lalu cari nama".
3. **Pecah teks per komentar/kalimat sebelum entity linking.** Jangan labeli satu thread ke satu pemain.
4. **`player_id` internal adalah satu-satunya kunci join.** Dilarang join berdasarkan nama.
5. **Data mentah terpisah dari data bersih.** `data/raw/` tidak pernah ditimpa.
6. **Angka tidak boleh membentuk skor kualitas.** Skor kualitas hanya dari teks. Angka = harga + validator.
7. **SoFIFA value/wage bukan harga pasar.** Hasil rumus EA, jangan dipakai sebagai target harga. Harga = market value Transfermarkt.
8. **Pemain dengan teks sedikit diberi label** `bukti tidak cukup` (< 10), `bukti terbatas` (10–29), `bukti cukup` (≥ 30). Jangan dinilai paksa. Pemain `bukti tidak cukup` **tidak boleh** masuk tabel kandidat.
9. **Evaluasi dulu sebelum dipakai** — sentiment dan entity linking harus diuji pada sampel berlabel manual sebelum masuk analisis.
10. **Setiap perubahan ambang dicatat** di `docs/decisions.md` beserta alasannya.
11. **Jangan simpan username atau data pribadi** penulis komentar.
12. **Patuhi `robots.txt`/ToS**, jangan menembus paywall, hanya data publik.
13. **Konfigurasi liga/musim/whitelist hanya di `config/config.yaml`**, jangan hardcode di kode scraper. Seed acak juga di config, bukan di kode.
14. **Daftar sampel pemain adalah file terkunci** di `data/processed/text_sample.parquet`, bukan dihasilkan ulang setiap skrip jalan. Setelah dikunci jangan diubah; kalau perlu revisi, buat versi baru dan beri tahu seluruh tim.
15. **Harga dilarang memFILTER populasi, tapi wajib menSTRATIFIKASI sampel teks.** Dua hal berbeda:
    - Populasi: jangan buang pemain karena mahal atau murah (`price_filter_enabled: false`).
    - Sampel teks: **wajib** berstrata per kuartil market value × kelompok posisi, dengan seed tetap. Tanpa ini sampel dikuasai pemain populer — bias yang justru ingin dicegah.
    - Sampling memakai **stratified sampling dengan seed tetap**, bukan acak murni: acak murni tidak bisa menjamin kuota per sel (posisi × kuartil) terpenuhi.
16. **Dilarang menyetel ambang supaya hasil terlihat bagus.** Tetapkan ambang sebelum melihat daftar kandidat; kalau disetel setelah eksplorasi, catat di `docs/decisions.md`.
17. **Nama ambigu tidak boleh dikaitkan hanya dari kecocokan nama.** "Silva", "Rodri", "Vini" butuh konteks klub/liga/rekan setim. Lihat `docs/PRD.md` §7 Tahap C.

## Konvensi kerja

- **Scraper wajib punya:** rate limit **≥ 1 detik per request**, retry dengan exponential backoff, caching, User-Agent yang wajar, dan logging jumlah hasil per pemain (supaya scraping kosong ketahuan, bukan hilang tanpa error).
- **Satu sumber rating saja** untuk validasi numerik. Mencampur FotMob dan FBref membuat z-score tidak bermakna.
- **`search.list` YouTube mahal** — pakai `playlistItems.list`. Kuota harian bisa habis dalam beberapa query.
- **Transfermarkt memblokir `requests` polos** (HTTP 405 + halaman verifikasi). Pakai `soccerdata` atau Playwright.
- **Reddit memblokir request tanpa auth** (HTTP 403 ke curl). 403 bukan bukti subreddit tidak ada; verifikasi lewat API ber-auth. Kalau akses Reddit bermasalah, jangan mencari jalan memutar — laporkan dan alihkan ke YouTube + artikel.
- **Gate pilot sebelum scraping penuh:** 20 pemain campuran bintang dan non-bintang, lalu cek manual 100 teks acak. Target relevansi retrieval ≥ 85%. Di bawah itu, perbaiki filter dulu.
- **Kredensial lewat `.env`**, jangan pernah masuk kode, commit, atau dokumen. `.env` wajib ada di `.gitignore`.
- **Dokumen berbahasa Indonesia.** Kode, nama variabel, dan komentar kode berbahasa Inggris.

## Aturan bahasa dan klaim

Berlaku untuk laporan, README, komentar kode, dashboard, dan jawaban ke tim.

- Jangan menulis **"membuktikan"**, **"pasti"**, atau **"terbukti"** untuk hasil yang berasal dari teks. Gunakan "mengindikasikan", "menunjukkan", "konsisten dengan".
- Rumusan inti: **teks mengindikasikan kualitas, angka memvalidasi performa, harga menunjukkan peluang.**
- **Daftar overhyped adalah analisis sekunder (avoid list)**, bukan hasil utama. Jangan ditempatkan setara dengan kandidat undervalued.
- **"Hidden gem" di Premier League dibaca sebagai *underrated***, bukan pemain tak dikenal. Cantumkan di bagian keterbatasan.
- **Setiap angka di laporan harus bisa ditelusuri ke skrip atau notebook di repo.** Jangan menulis angka dari ingatan.
- **Keterbatasan wajib ditulis:** sampel ±70 pemain (bukan seluruh liga), satu liga, satu musim, VADER + kamus aspek sederhana, sarkasme dan slang sulit dikenali, bias volume.
- **Kandidat yang pujian teksnya tidak sejalan dengan angka dilaporkan sebagai temuan**, bukan dibuang.

## Checklist sebelum menyatakan tugas selesai

- [ ] Hasil bisa direproduksi dari data mentah (`make pipeline`)
- [ ] Tidak ada join berdasarkan nama
- [ ] Tidak ada market value dipakai untuk memfilter populasi
- [ ] Sampel teks berstrata per kuartil harga dengan seed tetap
- [ ] Data mentah tidak tertimpa
- [ ] Ada angka evaluasi (relevansi retrieval, akurasi entity linking, akurasi sentiment) beserta contoh error
- [ ] Bahasa klaim sudah sesuai bagian "Aturan bahasa dan klaim"
- [ ] Perubahan keputusan sudah dicatat di `docs/decisions.md`

## Hal yang butuh keputusan manusia

Jangan diputuskan sendiri:

- Bentuk output yang dinilai dosen (laporan / presentasi / demo dashboard)
- Porsi kolom numerik agar dataset tetap "dominan string"
- Pemakaian X/Twitter (default: dilewati)
- Menambah anggota populasi di luar data terstruktur
- Menambah dependensi atau fitur di luar PRD

## Jika ragu

Berhenti dan tanyakan. Jangan menebak keputusan desain, jangan melonggarkan aturan di atas demi mengejar tenggat, dan jangan menyembunyikan masalah. Laporkan lebih awal kalau scraping, akses API, atau kualitas data bermasalah — jadwal hanya 1 minggu.

Kalau waktu tersisa, prioritasnya **evaluasi yang lebih kuat**, bukan fitur baru.

## Sebelum melanjutkan pekerjaan

1. Baca [`README.md`](README.md) bagian Status, lalu [`docs/PLAN-1WEEK.md`](docs/PLAN-1WEEK.md) untuk jadwal dan peran.
2. Cek `docs/decisions.md` — jangan ulangi perubahan ambang yang sudah ditolak.
3. Jalankan `make config` dan `git status` untuk memverifikasi state nyata sebelum mengklaim sesuatu berjalan.
