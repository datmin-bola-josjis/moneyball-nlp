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

| 2026-11-12 | Sumber teks Reddit: Arctic Shift, bukan API resmi | `src/scrape/arctic_shift_client.py` | Reddit API resmi butuh client_id/secret yang persetujuannya melewati tenggat 1 minggu. Diuji: `.json` balas 403, `old.reddit.com` balas halaman palsu, RSS hanya berisi post tanpa komentar dan ter-throttle ~1 request/30s. Pushshift 403, PullPush 526 (SSL). Arctic Shift: tanpa kredensial, cakupan musim 2025/26 terverifikasi, lag arsip 0 hari | Rafif |
| 2026-11-12 | Pesan "Timeout. Maybe slow down a bit" = rate limit, bukan timeout jaringan | jeda adaptif 8→240s, TIDAK menaikkan timeout socket | Terukur: error muncul dengan latensi 1-4 detik, dan query identik berhasil setelah jeda. Kalau dipercaya sebagai timeout jaringan, klien akan menaikkan timeout dan makin lambat tanpa memperbaiki apa pun | Rafif |
| 2026-11-12 | HTTP 422 RETRYABLE, HTTP 400 TIDAK | `NON_RETRYABLE_STATUS = {400,401,403,404}` | Arctic Shift mengirim HTTP 422 berisi pesan rate limit. Sempat salah klasifikasi sebagai error permanen sehingga run berhenti padahal akan berhasil. HTTP 400 ('aggregate is required') memang permanen dan harus gagal cepat agar tidak menghabiskan budget rate limit | Rafif |
| 2026-11-12 | Hitung thread pakai `posts/search/aggregate`, bukan paging | 1 request = 1 hitungan pasti | `posts/search` membatasi 100 hasil sehingga semua pengukuran awal CAPPED dan angka sebenarnya tidak diketahui. `aggregate=subreddit` mengembalikan count sebenarnya dalam 1 request: Haaland r/soccer 602 (bukan 100), r/MCFC 728 | Rafif |
| 2026-11-12 | `/api/comments/tree` TIDAK terpotong | 1 request per thread, limit=1000 | Diuji 2 thread: 982 komentar -> 770 nested (750 berisi); 543 -> 558 nested (101%). Selisih di thread pertama karena 212 komentar terhapus sebelum terarsip, bukan karena pemotongan. Ini yang membuat strategi post-first layak | Rafif |

## Perubahan setelah melihat data

| Tanggal | Ambang | Dari | Ke | Alasan (wajib, dengan angka) |
|---|---|---|---|---|
| — | — | — | — | — |

## Keputusan yang masih menggantung

| Item | Status | Perlu siapa |
|---|---|---|
| Porsi kolom numerik agar dataset tetap "dominan string" | terbuka | Dosen |
| Akses Reddit (persetujuan API) | terbuka, tenggat Hari 1 | B |
| Bentuk akhir yang dinilai (laporan / presentasi / demo) | terbuka, tenggat Hari 2 | Semua |
