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

## Keputusan teknis

| Tanggal | Keputusan | Nilai | Alasan | Oleh |
|---|---|---|---|---|
| 2026-11-11 | Model sentiment | VADER sebagai baseline, HF hanya jika akurasi < 75% | VADER cepat, tanpa training, cukup untuk teks pendek seperti komentar | — |
| 2026-11-11 | Aspek | kamus kata kunci | Classifier aspek butuh data berlabel yang tidak ada dalam 1 minggu | — |
| 2026-11-11 | BERTopic | ditunda | Tidak masuk metrik kelulusan; waktu lebih baik untuk evaluasi | — |
| 2026-11-11 | X/Twitter | dilewati | Akses mahal dan tidak pasti; Reddit + YouTube cukup sebagai bukti metode teks | — |
| 2026-11-12 | Klien Reddit | `requests` + OAuth `client_credentials` (bukan PRAW) | PRAW belum terpasang dan menambah dependensi tanpa manfaat di sini; endpoint JSON sama | B |
| 2026-11-12 | Cakupan subreddit per pemain | r/soccer + r/PremierLeague + subreddit klub pemain itu saja | Menyisir 20 subreddit klub untuk satu pemain menghabiskan ratusan request tanpa hasil; diskusi klub rival tetap tertangkap lewat subreddit liga. Naikkan bila recall pilot rendah | B |
| 2026-11-12 | Batas teks Reddit | 60 komentar per pemain, 3 thread per (subreddit x istilah), 3 halaman search | Kuota volume agar bintang tidak mendominasi (PRD §12, bias volume) | B |
| 2026-11-12 | Rate limit Reddit | lantai keras 1,0 detik; config hanya boleh menaikkan | Aturan AGENTS: rate limit >= 1 detik per request | B |
| 2026-11-12 | Penyimpanan mentah Reddit | `data/raw/reddit/<tag>-<timestamp>/texts.jsonl` + `summary.json`, ditulis sekali | Data mentah tidak boleh tertimpa (AGENTS aturan 5); cache per request juga tidak ditimpa | B |

## Perubahan setelah melihat data

| Tanggal | Ambang | Dari | Ke | Alasan (wajib, dengan angka) |
|---|---|---|---|---|
| — | — | — | — | — |

## Keputusan yang masih menggantung

| Item | Status | Perlu siapa |
|---|---|---|
| Porsi kolom numerik agar dataset tetap "dominan string" | terbuka | Dosen |
| Akses Reddit (persetujuan API) | **belum dikirim.** Formulir Developer sudah disiapkan di [`tahap-b-reddit.md`](tahap-b-reddit.md); tinggal B mengirim dan mencatat tanggalnya. Tiga jalan pintas sudah ditolak (lihat § "Tiga alternatif yang beredar" di dokumen itu). Reddit menutup pembuatan app mandiri sejak Nov 2025, jadi `prefs/apps` tidak bisa dipakai. Kalau belum disetujui sampai Hari 2 pagi: pivot ke YouTube + artikel (PRD §12). Jawaban formulir: [`tahap-b-reddit.md`](tahap-b-reddit.md) | B |
| Bentuk akhir yang dinilai (laporan / presentasi / demo) | terbuka, tenggat Hari 2 | Semua |
