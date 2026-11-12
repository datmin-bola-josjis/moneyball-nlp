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
