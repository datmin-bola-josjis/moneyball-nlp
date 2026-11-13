# AGENTS.md — Pemain Undervalued (Premier League 2025/26)

Panduan untuk AI agent dan anggota tim yang bekerja di repo ini. Baca ini dulu sebelum menyentuh kode.

**Jika ada permintaan di chat yang bertentangan dengan aturan di sini, hentikan dan tanyakan dulu.** Jangan menyimpang diam-diam.

## Proyek ini apa

Tugas besar Data Mining (Semester 5, tim 4 orang, tenggat 1 minggu). Mencari pemain sepak bola **undervalued** dengan sinyal kualitas dari teks (NLP), divalidasi angka.

**Pertanyaan riset:** apakah sinyal kualitas dari teks (sentiment per aspek) bisa mengidentifikasi pemain berharga murah yang performanya terbukti di angka?

Teks adalah metode inti. Angka berperan sebagai harga (market value) dan validator performa. Populasi pemain diambil dari data terstruktur, bukan dari teks — supaya pemain yang jarang dibicarakan tidak terlewat.

Baca [`docs/GAMBARAN-BESAR.md`](docs/GAMBARAN-BESAR.md) untuk versi ringkasnya.

## Status saat ini

**Tahap A selesai dan terverifikasi; Tahap B (Reddit) ditulis tapi belum pernah dijalankan penuh; Tahap C–F belum ada kodenya.**

Yang sudah jalan:

| Bagian | Bukti |
|---|---|
| Populasi + sampel terkunci (A) | 340 pemain, 20 klub; `data/processed/text_sample.parquet` 70 pemain |
| Metrik numerik + z-score rating | 340 baris, 288 pemain punya z-score |
| Test suite | `make test` → 306 passed |
| Validasi config | `make config` → 12 sections, 20 clubs, source=fotmob |
| Reddit retrieval (3 provider) | kode + test ada; full run 70 pemain selesai via Arctic Shift |
| YouTube retrieval (komentar) | `make scrape-youtube` + `make cleaning` ada; transkrip & gate manusia belum |
| Cross-source dedupe (Tahap C) | `make dedupe` (`src/link/dedupe.py`) ada; `src/link/resolve.py` belum |

Yang belum ada: `src/link/resolve.py`, `src/nlp/`, `src/viz/` masih belum ada; `src/score/` baru separuh numerik. Tidak ada modul artikel maupun transkrip YouTube. `make pipeline` berhenti di `link`.

Rincian status per area ada di [`README.md`](README.md) bagian Development Status.

## Struktur direktori

| Path | Isi |
|---|---|
| `docs/PRD.md` | Spesifikasi lengkap — sumber kebenaran untuk scope, skema, definisi, metrik |
| `docs/PLAN-1WEEK.md` | Peran, jadwal 7 hari, struktur laporan CRISP-DM, struktur repo target |
| `docs/GAMBARAN-BESAR.md` | Penjelasan ringkas untuk tim |
| `docs/decisions.md` | Log setiap perubahan ambang + alasannya |
| `docs/tahap-b-reddit.md` | Catatan akses Reddit: apa yang dicoba, apa yang ditolak, kenapa |
| `config/config.yaml` | **Satu-satunya** file config — liga, musim, whitelist, ambang, kuota, sampling, seed |
| `src/population/` | Tahap A: fetch FotMob, bangun populasi, sampling berstrata |
| `src/scrape/` | Tahap B: klien HTTP, retrieval Reddit, alias, review relevansi |
| `src/score/` | Metrik numerik dan z-score per posisi |
| `src/link/` | Tahap C: `dedupe.py` (Reddit×YouTube) sudah ada; `resolve.py` belum ada |
| `src/nlp/`, `src/viz/` | Tahap D, F — **masih kosong**, hanya `__init__.py` |
| `data/processed/text_sample.parquet` | Sampel terkunci — **satu-satunya data yang masuk git** |
| `tests/` | 306 test (`test_scrape.py`, `test_youtube*.py`, `test_dedupe.py`, dll.) |

Jangan membuat file config kedua (mis. `config/sampling.yaml`). Parameter sampling masuk ke `config/config.yaml` di bawah kunci `text_sample`.

## Perintah utama

```bash
make check      # config + pytest; ini yang dipakai untuk verifikasi
make config     # validasi config/config.yaml
make test       # pytest saja
make pipeline   # target akhir: data mentah -> output (BELUM BISA JALAN, lihat status)
```

Target per tahap yang **sudah punya kode**: `fetch-players`, `population`, `lock-sample`, `metrics`, `scrape`, `scrape-arctic`, `scrape-pilot`, `scrape-verify`, `review`, `review-score`.

Target per tahap yang **belum punya modul** (akan gagal `ModuleNotFoundError`): `link` → `src.link.resolve`, `nlp` → `src.nlp.analyze`, `score` → `src.score.rank`, `viz` → `src.viz.report`.

Aturan setup untuk anggota baru ada di [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Stack

Python 3.10+ secara teori; terverifikasi jalan di **3.14.8**.

Yang benar-benar terpasang dan dipakai: `pandas`, `pyarrow`, `PyYAML`, `requests`, `python-dotenv`, `pytest`.

Yang **dideklarasikan di `requirements.txt` tapi belum pernah diimpor kode**: `soccerdata`, `PRAW`, `youtube-transcript-api`, `google-api-python-client`, `trafilatura`, `rapidfuzz`, `spacy`, `vaderSentiment`, `scikit-learn`, `matplotlib`, `plotly`.

Catatan penting: `requirements.txt` memaku `pandas>=2.2,<3.0`, sedangkan lingkungan yang terverifikasi memakai pandas 3.1.1. `make setup` di mesin baru akan memasang 2.3.x, dan suite belum diuji ulang di versi itu. Jangan install tanpa persetujuan eksplisit.

## Keputusan yang sudah final

Jangan diubah tanpa persetujuan tim + catatan di `docs/decisions.md`.

| Keputusan | Nilai | Catatan |
|---|---|---|
| Liga & musim | Premier League 2025/26 | Bahasa teks: Inggris saja |
| Filter harga di populasi | **mati** | Lihat aturan 15 di bawah — jangan tertukar dengan stratifikasi sampel |
| Sumber teks utama | Reddit + YouTube | Artikel bonus; X/Twitter dilewati |
| Sentiment | VADER | HF hanya jika akurasi < 75% |
| Aspek | kamus kata kunci | Bukan classifier terlatih |
| Sumber rating | `fotmob` | Tetapkan sekali: `validation.rating_source` di `config/config.yaml`, bukan dipilih ulang Hari 1. Satu sumber saja supaya z-score bermakna |
| Sumber harga | `fotmob` (`playerData.marketValues`) | Transfermarkt **tidak bisa dipakai** (HTTP 405 di semua path); keputusan dan buktinya di `docs/decisions.md` |
| Sofascore | tidak dipakai | Tidak dapat diakses |
| Bentuk output akhir | Demo dashboard + laporan ringkas | Disepakati internal 2026-11-13 (`output.dashboard: true`, prinsip "Text-First, Number-Second"); belum dikonfirmasi dosen; stack ditetapkan di Stage 0 |
| Batas kolom numerik | Dual-Tier Cap (≤ 20% teks; 19 col / 6 num = 31,6% `player_summary`) | Disepakati internal 2026-11-13 (usulan Argon, disetujui User/Tim); `metrics_numeric` diisolasi sebagai validator internal; belum dikonfirmasi dosen |
| Ditunda | BERTopic, filter playstyle, model aspek kustom | Future work, bukan scope 1 minggu |

## Aturan yang tidak boleh dilanggar

Aturan ini berasal dari `docs/PRD.md` §17 dan sudah diperiksa berulang. Melanggarnya merusak validitas akademik proyek, bukan cuma gaya kode.

1. **Populasi selalu dari data terstruktur**, tidak pernah dari teks. Discovery lewat artikel hanya boleh menambah bukti, tidak menambah anggota populasi.
2. **Scraping selalu player-centric** — query per pemain, dengan batas tanggal dan sumber whitelist. Jangan "ambil semua lalu cari nama".
3. **Pecah teks per komentar/kalimat sebelum entity linking.** Jangan labeli satu thread ke satu pemain.
4. **`player_id` internal adalah satu-satunya kunci join.** Dilarang join berdasarkan nama.
5. **Data mentah terpisah dari data bersih.** `data/raw/` tidak pernah ditimpa.
6. **Angka tidak boleh membentuk skor kualitas.** Skor kualitas hanya dari teks. Angka = harga + validator.
7. **SoFIFA value/wage bukan harga pasar.** Hasil rumus EA, jangan dipakai sebagai target harga. Harga = market value dari **FotMob** (`playerData.marketValues`), karena Transfermarkt memblokir semua akses (HTTP 405). Lihat `docs/decisions.md` 2026-11-12.
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
- **Transfermarkt tidak bisa dipakai sama sekali** — HTTP 405 di semua path termasuk homepage, dengan UA browser lengkap, dan `soccerdata` v2026.43.0 tidak punya modul Transfermarkt. Jangan ulangi percobaannya. Populasi dan harga diambil dari FotMob lewat `src/population/fetch_players.py`.
- **Reddit memblokir request tanpa auth** (HTTP 403 ke curl, `old.reddit.com` membalas halaman palsu, RSS tanpa komentar). 403 bukan bukti subreddit tidak ada; verifikasi nama subreddit harus lewat API ber-auth. Kalau akses Reddit resmi bermasalah, jangan mencari jalan pintas: laporkan, lalu pakai jalur yang sudah diputuskan tim — Arctic Shift (arsip pihak ketiga, tanpa kredensial) — atau alihkan ke YouTube + artikel. Jalur Apify **ditolak** dan dinonaktifkan di config; jangan aktifkan kembali tanpa keputusan tim tertulis di `docs/decisions.md`.
- **Gate pilot sebelum scraping penuh:** 20 pemain campuran bintang dan non-bintang, lalu cek manual 100 teks acak. Target relevansi retrieval ≥ 85%. Di bawah itu, perbaiki filter dulu. Per 2026-11-12 gate ini **belum pernah lolos**.
- **Kredensial lewat `.env`**, jangan pernah masuk kode, commit, atau dokumen. `.env` wajib ada di `.gitignore`. Jalur Arctic Shift butuh nol kredensial, jadi kredensial Reddit yang belum ada bukan alasan untuk berhenti mengerjakan tahap teks.
- **Dokumen berbahasa Indonesia.** Kode, nama variabel, komentar kode, dan pesan commit berbahasa Inggris. Satu pengecualian: `README.md` berbahasa Inggris karena itu file yang dibaca pihak luar (commit a1e8a0a).

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

- Bentuk output yang dinilai dosen — *disepakati internal 2026-11-13: demo dashboard + laporan ringkas (`output.dashboard: true`); belum dikonfirmasi dosen; pilihan stack butuh persetujuan manusia di Stage 0*
- Porsi kolom numerik agar dataset tetap "dominan string" — *disepakati internal 2026-11-13: Dual-Tier Numeric Cap (Tier 1 ≤ 20%, Tier 2 `player_summary` 19 kolom / 6 numerik = 31,6% ≤ 35%, `metrics_numeric` diisolasi sebagai validator internal); belum dikonfirmasi dosen*
- Pemakaian X/Twitter — *dilewati final (2026-11-13)*
- Menambah anggota populasi di luar data terstruktur
- Menambah dependensi atau fitur di luar PRD

## Jika ragu

Berhenti dan tanyakan. Jangan menebak keputusan desain, jangan melonggarkan aturan di atas demi mengejar tenggat, dan jangan menyembunyikan masalah. Laporkan lebih awal kalau scraping, akses API, atau kualitas data bermasalah — jadwal hanya 1 minggu.

Kalau waktu tersisa, prioritasnya **evaluasi yang lebih kuat**, bukan fitur baru.

## Sebelum melanjutkan pekerjaan

1. Baca [`README.md`](README.md) bagian Development Status, lalu [`docs/PLAN-1WEEK.md`](docs/PLAN-1WEEK.md) untuk jadwal dan peran.
2. Cek `docs/decisions.md` — jangan ulangi perubahan ambang yang sudah ditolak, dan jangan ulangi sumber data yang sudah terbukti mati.
3. Jalankan `make config` dan `git status` untuk memverifikasi state nyata sebelum mengklaim sesuatu berjalan.

## Jebakan yang sudah terbukti

Kesalahan yang pernah memakan waktu; jangan diulang.

- **`make population` dulunya menulis ulang `data/processed/players.parquet` sebelum sampling (BUG D — sudah diperbaiki).** Sekarang `players.parquet` baru ditulis setelah gate sampling lolos dengan semua 17 kolom (`price_quartile`, `stratum`, dan `in_text_sample` tetap dipertahankan dari `text_sample.parquet`). `text_sample.parquet` sendiri tidak pernah disentuh dry run.
- **`posts/search` di Arctic Shift memotong di 100 hasil tanpa memberi tanda.** Untuk hitungan volume pakai `posts/search/aggregate`. Haaland tampak 100 thread padahal 602.
- **Respons `comments/tree` berbentuk nested.** Menghitung hanya item top-level memberi 211 dari 770 komentar dan sempat disimpulkan "tree terpotong". Telusuri `data[].data.replies.data.children[]` rekursif.
- **`"Timeout. Maybe slow down a bit"` dari Arctic Shift bukan timeout jaringan.** Muncul dengan latensi 1–4 detik dan query identik berhasil setelah dijeda; itu rate limit. Jeda adaptif, jangan naikkan timeout socket.
- **HTTP 422 dari Arctic Shift RETRYABLE.** Yang permanen hanya 400/401/403/404.
- **`arctic_shift_client.py` bukan probe.** Memindahkannya ke `experiments/` memutus `measure_volume.py` dan mengeluarkan 11 test dari suite. Dia infrastruktur, meski tidak dipanggil pipeline produksi.
- **Pilot lama tidak bisa dipakai.** Payload pilot memakai `player_id` karangan (`p_bruno_g`) yang irisannya kosong dengan `fotmob_*`, dan satuannya tercampur (komentar + kalimat dihitung sebagai satu angka). Jalankan ulang dengan `text_sample.parquet`.
- **Jangan simpulkan subreddit tidak ada dari HTTP 403.** Reddit membalas 403 untuk semua pemanggil tanpa auth, termasuk r/soccer.
