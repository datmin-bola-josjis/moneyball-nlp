# Catatan Keputusan

Satu baris per keputusan. Kolom "Alasan" yang kosong berarti keputusan masih menunggu.

Format tanggal: `YYYY-MM-DD`. Jangan hapus baris lama — tambahkan baris baru dan tandai keputusan yang digantikan.

## Ambang dan definisi

| Tanggal | Keputusan | Nilai | Alasan | Oleh |
|---|---|---|---|---|
| 2026-11-11 | Ambang awal (usulan) | kualitas ≥ p75, harga ≤ p40, buzz hidden gem ≤ p40, buzz overhyped ≥ p75 | Nilai awal PRD, belum diuji. Wajib ditinjau setelah eksplorasi distribusi | — |
| 2026-11-11 | Batas kecukupan teks | ≥30 cukup / 10–29 terbatas / <10 tidak cukup | Teks EPL melimpah; batas liga kecil akan over-include | — |
| 2026-11-11 | Filter harga di populasi | mati | Teks harus jadi penentu penuh; filter harga di depan akan membuang kandidat | — |
| 2026-11-11 | Sumber rating | satu sumber (FotMob **atau** FBref) | Mencampur sumber membuat z-score tidak bermakna | — |
| 2026-11-12 | Sumber harga: Transfermarkt → FotMob | `data_source.provider: fotmob` | Transfermarkt diblokir total (HTTP 405 semua path termasuk homepage, UA browser lengkap pun ditolak) dan `soccerdata` v2026.43.0 tidak punya modul Transfermarkt. FotMob punya market value **dan** rating di satu sumber, jadi aturan "satu sumber rating" tetap terpenuhi. PRD §6 perlu diperbarui | Rafif |
| 2026-11-12 | FotMob league & season ID | `league_id: 47`, `season_id: 27110` | Diverifikasi lewat `deepstats`: top scorer 2025/26 = Haaland 27 gol, 2024/25 = Salah 29 gol, jadi parameter season benar-benar dipakai. Endpoint `/api/data/leagues?id=47` **mengabaikan** season dan selalu memberi tabel 2026/27 — jangan dipakai verifikasi klub | Rafif |
| 2026-11-12 | Seed sampling | `random_seed: 20252026` | Stratified sampling wajib reproducible. Seed disimpan di config, bukan kode (AGENTS.md aturan 13). Tidak boleh diubah setelah sampel dikunci | Rafif |

## Keputusan teknis

| Tanggal | Keputusan | Nilai | Alasan | Oleh |
|---|---|---|---|---|
| 2026-11-12 | Kode posisi 83 = FWD, bukan MID | `positions.py` 83 → "Right Winger" | deepstats memberi label "Right Midfielder", tapi 22 dari 26 pemain berkode 83 melaporkan "Right Winger" di playerData (Saka, Salah, Kudus, Madueke). Profil per-90 mereka cocok dengan kode winger: tackle 1.58 vs 1.57 (kode 87 Left Winger), sementara kode gelandang 2.06–2.38. Memetakan ke MID membandingkan winger dengan gelandang tengah dan menggeser 26 pemain. Sampel teks dibuat ulang setelah perbaikan | Rafif |
| 2026-11-12 | Sumber posisi = deepstats, bukan playerData | `position` dari baris statistik musim | `playerData` merujuk klub dan musim saat ini: untuk Salah isinya Süper Lig 2026/2027 dan Trabzonspor, bukan Liverpool 2025/26. Label posisinya juga agregat karier (RW 31 kali, Striker 12, AM 5), bukan posisi musim ini. Dipakai hanya untuk memverifikasi label, bukan sebagai sumber utama | Rafif |
| 2026-11-12 | Semantik statistik diverifikasi, tidak dipercaya dari nama | lihat `src/score/metrics.py` | `total_tackle` dan `accurate_pass` ternyata SUDAH per-90 walau namanya tanpa akhiran. `goals`, `xG`, `xA` adalah total dan cocok dengan `per_90 x menit/90` (295/314 cocok). `saves` hanya memuat 20 kiper dengan ≥1800 menit — kiper di bawah itu bernilai null, bukan nol | Rafif |
| 2026-11-11 | Model sentiment | VADER sebagai baseline, HF hanya jika akurasi < 75% | VADER cepat, tanpa training, cukup untuk teks pendek seperti komentar | — |
| 2026-11-11 | Aspek | kamus kata kunci | Classifier aspek butuh data berlabel yang tidak ada dalam 1 minggu | — |
| 2026-11-11 | BERTopic | ditunda | Tidak masuk metrik kelulusan; waktu lebih baik untuk evaluasi | — |
| 2026-11-11 | X/Twitter | dilewati | Akses mahal dan tidak pasti; Reddit + YouTube cukup sebagai bukti metode teks | — |
| 2026-11-12 | Klien Reddit | `requests` + OAuth `client_credentials` (bukan PRAW) | PRAW belum terpasang dan menambah dependensi tanpa manfaat di sini; endpoint JSON sama | B |
| 2026-11-12 | Cakupan subreddit per pemain | r/soccer + r/PremierLeague + subreddit klub pemain itu saja | Menyisir 20 subreddit klub untuk satu pemain menghabiskan ratusan request tanpa hasil; diskusi klub rival tetap tertangkap lewat subreddit liga. Naikkan bila recall pilot rendah | B |
| 2026-11-12 | Batas teks Reddit | 60 komentar per pemain, 3 thread per (subreddit x istilah), 3 halaman search | Kuota volume agar bintang tidak mendominasi (PRD §12, bias volume) | B |
| 2026-11-12 | Rate limit Reddit | lantai keras 1,0 detik; config hanya boleh menaikkan | Aturan AGENTS: rate limit >= 1 detik per request | B |
| 2026-11-12 | Penyimpanan mentah Reddit | `data/raw/reddit/<tag>-<timestamp>/texts.jsonl` + `summary.json`, ditulis sekali | Data mentah tidak boleh tertimpa (AGENTS aturan 5); cache per request juga tidak ditimpa | B |
| 2026-11-12 | Provider Reddit untuk teks | OAuth saja. Actor Apify `automation-lab/reddit-scraper` **dinonaktifkan** setelah ditinjau ulang | Keputusan tim sebelumnya menerima risiko pelanggaran, tetapi ditinjau ulang di hari yang sama: actor ini melanggar Reddit User Agreement §7 dan PRD §13, sedangkan AGENTS.md mewajibkan patuh ToS dan melarang jalan pintas saat akses Reddit bermasalah. Kode dan hasil pilot disimpan sebagai catatan; `text_sources.reddit.apify.enabled` disetel `false` dan tidak boleh diaktifkan tanpa keputusan tim baru yang tertulis di sini. Jalur teks resmi: OAuth bila disetujui, atau YouTube + artikel (PRD §12) | B |

## Perubahan setelah melihat data

| Tanggal | Ambang | Dari | Ke | Alasan (wajib, dengan angka) |
|---|---|---|---|---|
| 2026-11-12 | Cakupan aktor Apify (`max_posts_per_player`, `timeFilter`, `sort`) | 5 post, `timeFilter: all` | 15 post, `timeFilter: year`, `sort: top` | Diukur pada pilot: hanya 35% item yang dikembalikan jatuh di dalam musim (207/585); `timeFilter: all` mengembalikan saga transfer Jun-Okt 2026 yang seluruhnya gugur. Dengan 15 post: 8/15 post dan 81 komentar in-season, tetapi hanya ~13 komentar per pemain yang menyebut pemain itu. Artinya hampir semua pemain akan berlabel `bukti terbatas` (10-29), bukan `bukti cukup` (>=30). Biaya terukur: $0.155/pemain, 70 pemain = $10.87 - melebihi sisa kredit Apify, jadi jalur ini hanya sanggup ~20 pemain. |
| 2026-11-12 | Biaya pilot Apify (dihentikan) | $0.8717 terpakai dari kredit gratis $5 | Dihabiskan untuk 6 run pilot + 1 run 25 pemain yang dihentikan di 4/25. Sisa kredit $4.128 tidak dipakai. Bukti mentah tiap run ada di `data/raw/reddit/` dan run yang terhenti tidak menghasilkan file interim. | B |
| — | — | — | — | — |

## Keputusan yang masih menggantung

| Item | Status | Perlu siapa |
|---|---|---|
| Porsi kolom numerik agar dataset tetap "dominan string" | terbuka | Dosen |
| Akses Reddit (persetujuan API) | **belum dikirim.** Formulir Developer sudah disiapkan di [`tahap-b-reddit.md`](tahap-b-reddit.md); tinggal B mengirim dan mencatat tanggalnya. Tiga jalan pintas sudah ditolak (lihat § "Tiga alternatif yang beredar" di dokumen itu). Reddit menutup pembuatan app mandiri sejak Nov 2025, jadi `prefs/apps` tidak bisa dipakai. Kalau belum disetujui sampai Hari 2 pagi: pivot ke YouTube + artikel (PRD §12). Jawaban formulir: [`tahap-b-reddit.md`](tahap-b-reddit.md) | B |
| Bentuk akhir yang dinilai (laporan / presentasi / demo) | terbuka, tenggat Hari 2 | Semua |
