# Rencana Kerja — 1 Minggu, 4 Orang

Pendamping [`PRD.md`](PRD.md). Dokumen ini yang dipakai sehari-hari; PRD menyimpan alasan dan definisi.

**Target satu minggu:** satu pipeline yang jalan dari ujung ke ujung dengan data yang lebih kecil. Bukan semua fitur.

---

## 1. Yang dipangkas dari versi penuh

| PRD penuh (4–5 minggu) | Versi 1 minggu |
|---|---|
| 3 sumber teks + X | 2 sumber teks: Reddit dan YouTube (komentar; transkrip jika sempat). Artikel scouting bonus |
| ±200 pemain | Roster penuh 20 klub untuk data angka (murah); teks hanya untuk ±60–80 pemain (campuran bintang dan non-bintang), maksimal 50–100 teks per pemain |
| Aspect-based sentiment dengan model terlatih | Sentiment pakai model jadi (VADER atau model Hugging Face) + aspek lewat kamus kata kunci (finishing, passing, bertahan, stamina, dribbling) |
| BERTopic, hidden gem flag, filter kebutuhan klub | Dibuang atau jadi future work |
| Evaluasi 200 teks berlabel | 100 teks berlabel manual, dibagi 4 orang (masing-masing 25) |

**Risiko yang harus diputuskan di Hari 1:** akses API Reddit sering butuh persetujuan dan bisa lambat. Kalau Hari 1 tidak ada jalan masuk yang pasti, YouTube jadi sumber utama dan artikel scouting jadi sumber kedua — dan itu ditulis di laporan.

---

## 2. Pembagian peran

| Orang | Peran | Tugas utama |
|---|---|---|
| **A** | Data populasi dan angka | Roster Premier League 2025/26 via `soccerdata`/Transfermarkt/FotMob; `player_id`, alias nama, market value, rating, menit main. Setelah Hari 3 pindah ke validasi angka dan visualisasi |
| **B** | Scraper Reddit | Subreddit klub, r/soccer, r/PremierLeague; query per pemain; pecah per komentar dan kalimat. Setelah scraping: labeling manual dan bagian metodologi laporan |
| **C** | Scraper YouTube dan artikel | Komentar dan transkrip dari channel whitelist; artikel dengan `trafilatura`. Setelah scraping: cleaning, dedupe, dan labeling manual |
| **D** | NLP dan skoring | Entity linking, sentiment, aspek, Skor Kualitas Teks, kandidat undervalued. Pemegang struktur repo dan merge |

Semua orang menulis bagian laporannya sendiri, dan **semua ikut labeling**. Labeling bukan pekerjaan satu orang — kalau ditumpuk ke D, Hari 4 akan macet.

**Aturan merge sederhana:** D adalah satu-satunya yang merge ke `main`. Orang lain bekerja di branch sendiri dan membuka PR yang kecil. Tidak ada force push ke `main`.

---

## 3. Jadwal 7 hari

| Hari | Target | Penanggung jawab | Selesai bila |
|---|---|---|---|
| **1** | Kunci skema tabel (`players`, `texts`), daftar sampel 60–80 pemain, keputusan Reddit/YouTube, config liga, setup repo | D + A | `docs/PRD.md` tak berubah lagi; `data/processed/text_sample.parquet` ada dan dikunci |
| **2** | Scraping pilot 20 pemain (campuran bintang dan non-bintang). Cek manual 100 teks acak: apakah benar membahas pemain itu | B, C | Laporan relevansi retrieval ≥ 85% pada sampel pilot, atau daftar masalah konkret |
| **3** | Perbaiki filter dari pilot, scraping penuh 60–80 pemain. Entity linking dan sentiment mulai di data yang sudah masuk | B, C + D | Scraper penuh jalan tanpa intervensi manual |
| **4** | Scraping dan cleaning selesai. Aspek dan Skor Kualitas Teks jadi. Labeling manual 100 teks | semua | `text_analysis` terisi; 100 label manual terkumpul di file terpisah |
| **5** | Join dengan market value dan rating, validasi angka, kandidat undervalued. Hitung akurasi sentiment | A + D | Tabel kandidat keluar dengan kolom validasi |
| **6** | Visualisasi (scatter, heatmap aspek per posisi, tabel top 10–20) dan penulisan laporan | A + B + C | 3–4 visual final + draf laporan lengkap |
| **7** | Buffer: perbaiki, rapikan, latihan presentasi. **Jangan tambah fitur baru** | semua | Laporan siap kumpul |

**Dua titik rawan**

- **Hari 1** — kalau skema telat, semua tertahan. Skema dan sampel pemain harus terkunci sebelum orang lain mulai menulis kode.
- **Hari 3** — kalau scraping baru benar-benar jalan di Hari 4, jadwal geser dan Hari 6 jadi sempit. Perbaikan Hari 3 harus selesai setengah hari.

---

## 4. Bentuk hasil yang dinilai

Hasil utama: **laporan ala paper pendek (data mining)**. Dashboard Streamlit hanya bonus.

**Struktur laporan (alur CRISP-DM)**

1. **Latar belakang dan pertanyaan riset** — masalah efisiensi anggaran klub, mengapa teks dipakai.
2. **Pemahaman data dan pengumpulan** — sumber, ukuran dataset, periode, proses retrieval per pemain, keputusan sampel.
3. **Preprocessing** — cleaning, dedupe, filter bahasa/panjang, entity linking per kalimat, contoh sebelum-sesudah.
4. **Pemodelan** — sentiment model, kamus aspek, formula Skor Kualitas Teks, bobot sumber, definisi buzz.
5. **Evaluasi** — akurasi sentiment pada 100 teks berlabel, relevansi retrieval, Cohen's κ antar-anotator, dan metrik bukti utama (berapa persen kandidat teks yang juga di atas median rating posisi).
6. **Hasil** — tabel kandidat, scatter, heatmap, korelasi buzz vs market value, avoid list overhyped.
7. **Kesimpulan dan keterbatasan** — sampel bukan seluruh liga, hidden gem di EPL berarti underrated, persentil per posisi tidak stabil di ekor, keterbatasan akses sumber, dan tidak ada penyesuaian antar liga.

Dosen data mining biasanya menilai proses dan evaluasi, bukan kecanggihan model. Bagian 3 dan 5 jangan dikorbankan demi visualisasi.

**Dashboard (opsional):** tabel kandidat yang bisa difilter per posisi, scatter plot, detail per pemain. Kalau Hari 6 belum siap, cukup notebook dengan visual rapi.

**Batas kelayakan minimum di akhir minggu**

- dataset teks yang bersih;
- bukti entity linking dan sentiment dievaluasi manual;
- satu tabel kandidat undervalued dengan validasi angka;
- 3–4 visual.

---

## 5. Definisi "selesai" per orang

| Orang | Selesai bila |
|---|---|
| A | `players` + `metrics_numeric` lengkap, `player_id` unik, alias nama bisa dipakai scraper, visualisasi final ada |
| B | `texts` dari Reddit dengan `unit_type=comment` dan `=sentence`, kolom `created_at` dan `player_id` terisi, laporan relevansi retrieval ada |
| C | `texts` dari YouTube (+artikel bonus) dengan metadata `channel`/`situs`, hasil dedupe terhadap Reddit, tabel cleaning terdokumentasi |
| D | `text_analysis`, `player_summary`, tabel kandidat, dan skrip yang menjalankan seluruh pipeline dengan satu perintah |

---

## 6. Yang paling sering bikin proyek ini gagal

| Jebakan | Pencegahan |
|---|---|
| Menunggu Reddit sampai Hari 3 | Putuskan Hari 1. Punya jalan masuk atau tidak. Kalau tidak, pivot ke YouTube malam itu |
| Skema tabel berubah setelah scraping dimulai | Skema dikunci Hari 1. Kolom baru boleh ditambah, kolom lama tidak diubah namanya |
| Sampel pemain diganti setelah melihat hasil | Daftar sampel adalah file terkunci dan dicatat tanggal kuncinya |
| Labeling ditumpuk ke satu orang | 25 teks per orang, selesai di Hari 4 sebelum malam |
| Menambah fitur di Hari 7 | Dilarang. Hari 7 hanya perbaikan, perapian, latihan presentasi |
| Menilai pemain dengan teks 3 kalimat | Batas kecukupan teks dijalankan: < 10 tidak dinilai, 10–29 bertanda terbatas |
| Angka mulai diperlakukan sebagai skor kualitas | Skor kualitas hanya dari teks. Angka hanya harga dan validator |

---

## 7. Struktur repo yang disarankan

```text
.
├── AGENTS.md                    # panduan agent, dari PRD §17
├── README.md                    # cara jalan: config, perintah pipeline
├── Makefile                     # `make pipeline` = satu perintah dari mentah ke output
├── config/
│   └── config.yaml              # league, season, whitelist, ambang, kuota
├── docs/
│   ├── PRD.md
│   ├── PLAN-1WEEK.md
│   └── decisions.md             # catatan setiap perubahan ambang + alasan
├── data/
│   ├── raw/                     # jangan pernah ditimpa
│   └── processed/
│       ├── text_sample.parquet  # daftar sampel terkunci
│       └── *.parquet
├── src/
│   ├── population/              # Tahap A
│   ├── scrape/                  # Tahap B (reddit, youtube, article)
│   ├── link/                    # Tahap C
│   ├── nlp/                     # Tahap D
│   ├── score/                   # Tahap E
│   └── viz/                     # Tahap F
├── notebooks/                   # eksplorasi hanya, bukan pipeline
├── reports/
│   ├── figures/
│   └── laporan.md
└── tests/                       # minimal: alias matching, filter tanggal, skema tabel
```

---

## 8. Satu pertanyaan yang menentukan banyak hal

Dosen meminta bentuk apa: laporan tertulis, presentasi, atau demo dashboard?

- Kalau **laporan**, dashboard bisa dibuang sepenuhnya dan waktunya dipakai untuk evaluasi yang lebih kuat — itu justru nilai tambah.
- Kalau **demo**, dashboard minimal (tabel + scatter + filter posisi) dikerjakan Hari 6 pagi, bukan Hari 7.

Jawab sebelum Hari 2. Jawabannya memindahkan beberapa jam kerja yang bisa menyelamatkan bagian evaluasi.
