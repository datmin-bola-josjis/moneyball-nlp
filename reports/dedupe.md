# Dedupe silang Reddit × YouTube (Tahap C)

Laporan ini dibuat oleh `src/link/dedupe.py`. Angka di bawah hanya berlaku
untuk dua file masukan yang disebut di sini, bukan untuk run lain.

## Masukan

| Sumber | File | Baris | Komentar | Kalimat |
|---|---|---|---|---|
| Reddit | `texts_reddit_full.jsonl` | 7061 | 3442 | 3619 |
| YouTube | `texts_youtube_full.jsonl` | 2159 | 1054 | 1105 |

## Aturan yang dipakai

- Duplikat = teks dengan `text_clean_hash` sama **untuk pemain yang sama**.
  Satu komentar yang menyebut dua pemain tetap dihitung dua kali, karena
  itu dua tautan entitas yang benar, bukan duplikat.
- Komentar dibandingkan dengan komentar, kalimat dengan kalimat. Komentar
  dan kalimatnya sendiri memang berbagi hash; menyamakan keduanya akan
  menghapus unit yang dipakai analisis sentimen.
- Hanya antar sumber. Duplikat **komentar** di dalam satu sumber sudah
  dibuang scraper lewat `text_clean_hash`. Kalimat identik yang muncul di
  dua komentar berbeda tidak tertangani di sini; jumlahnya dilaporkan di
  bawah, bukan dibuang diam-diam.
- Bila duplikat ditemukan, baris **Reddit** dipertahankan dan salinan
  YouTube dibuang. Teksnya identik, jadi pilihan ini tidak mengubah
  sentimen; Reddit dipilih karena sumber utamanya (PRD §7).

## Hasil

| Yang dibuang | Jumlah |
|---|---|
| Komentar YouTube yang teksnya sama dengan Reddit | 0 |
| Kalimat YouTube yang teksnya sama dengan kalimat Reddit | 0 |
| Kalimat YouTube yang komentar induknya dibuang | 0 |

| Yang dipertahankan | Baris |
|---|---|
| Reddit | 7061 |
| YouTube | 2159 |
| **Total** | **9220** |

**Tidak ada duplikat silang yang ditemukan.** Ini temuan, bukan
kegagalan: komentar Reddit dan komentar YouTube hampir tidak pernah
identik kata per kata, jadi nol adalah hasil yang diharapkan pada
korpus ini. Nilainya ada pada buktinya — bukan pada jumlah yang dibuang.

## Mengapa cakupannya dibatasi

Angka berikut dihitung dari masukan dan **tidak** dipakai untuk membuang
apa pun. Fungsinya menunjukkan bahwa dedupe naif akan merusak data:

| Pola | Reddit | YouTube |
|---|---|---|
| Baris | 7061 | 2159 |
| Hash unik | 5792 | 1589 |
| Hash dipakai lebih dari sekali | 1136 | 565 |
| Hash dipakai lebih dari satu pemain | 330 | 11 |
| Hash dipakai komentar **dan** kalimatnya | 831 | 556 |
| Teks sama untuk pemain yang sama (dalam satu sumber) | 7 | 0 |

`drop_duplicates('text_clean_hash')` akan menghapus semua baris pada dua
baris tengah tabel itu — kalimat yang sah dan tautan pemain yang benar.

Baris terakhir adalah duplikat yang seharusnya sudah dibuang scraper. Untuk
**komentar** memang sudah nol. Yang tersisa adalah **kalimat** yang sama di
dua komentar berbeda pada satu pemain: dua orang mengutip kalimat yang sama,
atau teks berita yang diposting ulang. Dedupe ini tidak menyentuhnya karena
cakupannya hanya antar sumber; kalau D ingin bobot sentimen tidak dihitung
dua kali, saring di tahap agregasi per pemain.

## Yang tidak diubah

- File masukan hanya dibaca, tidak pernah ditimpa (aturan 5).
- Duplikat komentar di dalam satu sumber tidak disentuh; itu tugas scraper.
- Baris kalimat yang komentar induknya bertahan tetap ada.

## Perintah

```bash
make dedupe                              # default: tag full untuk kedua sumber
make dedupe REDDIT_TAG=partial26         # uji coba pada data pilot
```

Keluaran: `data/processed/texts_deduped.parquet`.
