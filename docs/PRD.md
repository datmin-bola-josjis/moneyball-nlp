# PRD — Pencarian Pemain Undervalued Berbasis Sinyal Kualitas dari Teks

| | |
|---|---|
| **Versi** | 2.0 (scope 1 minggu, 4 orang) |
| **Tanggal** | 11 November 2026 |
| **Status** | Draft untuk dikunci di Hari 1 |
| **Konteks** | Tugas besar Data Mining, Semester 5 |
| **Prototipe** | Premier League 2025/26 — satu liga, satu musim |
| **Dokumen terkait** | [`PLAN-1WEEK.md`](PLAN-1WEEK.md) (peran & jadwal), [`config.yaml`](../config/config.yaml) (parameter liga), [`decisions.md`](decisions.md) (catatan ambang) |

> **Cara baca.** Dokumen ini adalah spesifikasi proyek. Bagian yang ditandai **[1 minggu]** adalah versi yang benar-benar dikerjakan sekarang; versi penuhnya (4–5 minggu, 3–4 sumber teks, ±200 pemain) disimpan sebagai arah pengembangan dan disebut eksplisit di mana ia dipangkas.

---

## 1. Ringkasan

Proyek analisis data berbasis teks (NLP) untuk menemukan pemain sepak bola **undervalued**: pemain yang diakui berkualitas dalam teks, harganya masih rendah, dan kualitas itu terbukti di angka.

Teks adalah metode inti. Angka berperan ganda sebagai harga (market value) dan sebagai validator performa. Populasi pemain sengaja diambil dari data terstruktur, bukan dari teks, supaya pemain yang jarang dibicarakan tidak terlewat.

Tujuan akhir: daftar kandidat pemain yang layak dibeli klub dengan anggaran terbatas, beserta bukti mengapa.

Dataset dominan string dan analisis utama berbasis sentiment/NLP, sesuai penekanan mata kuliah.

## 2. Tujuan

- **Bisnis:** daftar kandidat pemain berperforma baik dengan harga dan gaji rendah.
- **Akademik:** dataset dominan string dengan analisis utama berbasis sentiment dan NLP.
- **Portfolio:** satu pipeline end-to-end yang bisa dijalankan ulang dari data mentah sampai output (populasi, scraping, entity linking, NLP, validasi, visualisasi).

## 3. Pertanyaan riset

**Utama:**

> Apakah sinyal kualitas dari teks (sentiment per aspek dan playstyle) bisa mengidentifikasi pemain berharga murah yang performanya terbukti di angka?

**Pendukung:**

1. Apakah buzz (volume pembicaraan) berkorelasi dengan market value?
2. Aspek apa yang paling sering dipuji atau dikritik per posisi?
3. *(Sekunder)* Siapa pemain overhyped — buzz tinggi, performa biasa — sebagai daftar yang harus dihindari?

## 4. Scope

**In scope**

- Prototipe: Premier League musim 2025/26, 20 klub, musim sudah selesai (berakhir Mei 2026) sehingga statistik penuh dan stabil.
- Populasi angka: seluruh pemain Premier League 2025/26 dengan menit main ≥ 900.
- **[1 minggu]** Populasi teks: ±60–80 pemain hasil sampling berlapis dari populasi angka (lihat §7 Tahap A), bukan seluruh populasi.
- **[1 minggu]** Maksimal 50–100 teks per pemain, dengan kuota per sumber.
- Rentang tanggal teks: 1 Juli 2025 – 31 Mei 2026.
- Teks berbahasa Inggris.
- Ekspansi ke liga lain (Championship, Eredivisie, Belgian Pro League) hanya setelah pipeline stabil — di luar fase ini.

**Out of scope**

- Liga selain Premier League pada fase prototipe.
- Data historis all-time, dan musim 2026/27 yang masih berjalan saat proyek dikerjakan.
- Prediksi hasil pertandingan.
- Penyesuaian kekuatan antar liga (belum relevan selama hanya satu liga).
- Rekomendasi transfer siap pakai — output hanya kandidat analitis, bukan keputusan pembelian.
- X/Twitter (dilewati, lihat §6 dan §16).
- **[1 minggu]** BERTopic/topic modeling, aspect-based sentiment dengan model khusus, filter kebutuhan klub berbasis playstyle — ditunda ke future work (lihat §7 Tahap D dan E).

## 5. Prinsip desain

1. **Populasi dipisah dari penilaian.** Daftar pemain berasal dari data terstruktur (roster), bukan dari teks, supaya pemain yang jarang dibahas tidak terlewat.
2. **Scraping player-centric.** Teks dicari per pemain di dalam populasi, bukan "ambil semua lalu cari nama di dalamnya".
3. **Buzz rendah adalah sinyal, bukan kekurangan data.** Pemain dengan teks di bawah batas minimal diberi label "bukti tidak cukup", bukan dinilai paksa dengan sedikit teks.
4. **Teks menghasilkan sinyal kualitas, angka menyediakan harga dan validasi.** Skor utama berasal dari teks; angka tidak boleh mendominasi dan tidak boleh dipakai untuk membentuk skor kualitas.
5. **Setiap ambang bersifat terukur dan tercatat.** Persentil dan batas teks adalah nilai awal; setiap perubahan dicatat beserta alasannya.

## 6. Sumber data

Kolom **Tier** menandai apa yang dikerjakan dalam 1 minggu: `W` wajib, `B` bonus jika waktu sisa, `—` dilewati.

| Tier | Jenis | Sumber | Isi | Peran |
|---|---|---|---|---|
| W | Populasi | Transfermarkt, FBref/FotMob via `soccerdata` | Roster, posisi, umur, klub, menit main | Daftar pemain target |
| W | Teks (utama) | r/soccer, r/PremierLeague, dan 20 subreddit klub Premier League | Komentar post-match, player ratings, thread diskusi | Sentiment per aspek |
| W | Teks (utama) | YouTube channel whitelist | Komentar; transkrip jika waktu memungkinkan | Sentiment per aspek, bukti spesifik |
| B | Teks (pelengkap) | Artikel scouting/analisis (whitelist 5–10 situs) | Isi artikel | Penilaian mendalam, bukti spesifik |
| — | Teks (tambahan) | X/Twitter | Tweet | Dilewati pada fase ini |
| B | Kategorikal | SoFIFA | Playstyles, roles, posisi, ID pemain | Profil gaya main |
| W | Numerik (harga) | Transfermarkt | Market value, kontrak | Biaya |
| W | Numerik (validator) | FotMob, FBref/Understat | Rating per match, stat per 90, xG, xA | Validasi performa |

**Catatan penting**

- Value dan wage SoFIFA adalah hasil rumus EA, **bukan harga pasar**. Jangan pernah dipakai sebagai target harga.
- Sofascore tidak dipakai (tidak dapat diakses); diganti FotMob.
- Hanya **satu sumber rating** untuk validasi numerik, supaya z-score antar sumber tidak tercampur. Jika sumber utama gagal di Hari 1, ganti seluruhnya — jangan gabung dua sumber.
- Daftar subreddit klub, channel YouTube, dan situs artikel disimpan sebagai whitelist di config, bukan di kode.

## 7. Pipeline

### Tahap A — Populasi

1. Ambil roster 20 klub Premier League 2025/26 dari Transfermarkt/FBref/FotMob (via `soccerdata`).
2. Buat `player_id` internal sebagai satu-satunya kunci join. Simpan alias: dengan/tanpa aksen, nama pendek, julukan.
3. Filter wajib: menit main ≥ 900.
4. Filter harga: **mati**, teks menjadi penentu penuh. Persentil market value dihitung setelah skor teks jadi, bukan sebagai prasyarat masuk populasi.
5. **[1 minggu] Sampling pemain untuk jalur teks.** Populasi angka tetap utuh (murah, tidak perlu sampling). Teks dikerjakan untuk ±60–80 pemain hasil sampling berlapis, supaya sampel tidak hanya berisi bintang:
   - stratifikasi: 4 kelompok posisi (GK, DEF, MID, FWD) × kuartil market value di dalam liga;
   - target ±15–20 pemain per kelompok posisi, minimal 4 pemain per sel (posisi × kuartil) bila tersedia;
   - daftar sampel **dikunci di Hari 1** dan tidak diubah setelah scraping dimulai.

   Alasan: kalau sampel teks hanya berisi pemain populer, pertanyaan riset utama kehilangan dasar. Sampel yang dikunci lebih dulu juga melindungi dari tuduhan memilih kandidat setelah melihat hasil.
6. **[1 minggu] Catat batasnya.** Semua temuan berbasis teks berlaku untuk sampel, bukan untuk seluruh 20 klub. Ini ditulis di bagian keterbatasan laporan.

> Estimasi populasi: maksimum teoretis 20 klub × 38 laga × 11 slot × 90 menit ÷ 900 menit ≈ 836 slot; realistis sekitar 300–500 pemain yang lolos ambang 900 menit. Jumlah aktual dipakai apa adanya — data angka tidak mahal. Angka 150–250 pada draf awal terlalu konservatif dan tidak dipakai sebagai target.

### Tahap B — Retrieval teks (per pemain)

- **Reddit.** Subreddit klub + r/soccer + r/PremierLeague, query nama/alias dibatasi rentang musim. Pecah per komentar lalu per kalimat. **Jangan** melabeli satu thread penuh ke satu pemain.
- **YouTube.** Ambil video dari channel whitelist via `playlistItems.list`; filter judul yang memuat nama pemain; ambil komentar, transkrip jika memungkinkan. `search.list` mahal kuotanya dan dihindari.
- **Artikel (bonus).** URL dari sitemap/RSS/halaman tag situs whitelist, ekstrak dengan `trafilatura`. Masuk jika nama ada di judul atau ≥ 3 kali di isi. Tidak menembus paywall.
- **Discovery (bonus).** Kumpulkan artikel "hidden gems / underrated players", ekstrak nama dengan NER, cocokkan ke populasi. Hanya bukti tambahan — tidak pernah menambah anggota populasi.

### Tahap C — Filter dan entity linking

- Disambiguasi nama dengan konteks klub/liga/rekan setim.
- Filter tanggal (di dalam musim), bahasa (Inggris), dedupe, panjang minimal ≥ 8–10 kata, buang spam/bot.
- Entity linking tingkat kalimat: NER + fuzzy matching (`rapidfuzz`) + kunci tambahan (klub, tanggal lahir).
- Batas kuota teks per pemain per sumber, supaya bintang tidak mendominasi volume.

### Tahap D — NLP

- **[1 minggu]** Sentiment kalimat memakai model siap pakai: VADER (baseline cepat) dan/atau model Hugging Face, dipilih berdasarkan hasil uji pada 100 teks berlabel.
- **[1 minggu]** Aspek ditentukan lewat kamus kata kunci per aspek (finishing, passing, bertahan, stamina, dribbling, dan seterusnya), bukan classifier aspek terlatih. Kalimat tanpa kata kunci aspek tetap dihitung untuk sentiment umum.
- **[1 minggu]** Hitung `buzz_volume` per pemain (jumlah teks valid, dinormalisasi terhadap total populasi).
- Topic modeling (BERTopic) **ditunda** ke future work.

### Tahap E — Skoring dan validasi

1. **Skor Kualitas Teks** per pemain: rata-rata sentiment aspek yang relevan untuk posisinya, tertimbang kepercayaan (jumlah teks, bobot sumber). Rentang −1 sampai 1.
2. Pemain di bawah batas minimal teks diberi label bertingkat — `bukti cukup` / `bukti terbatas` / `bukti tidak cukup` — dan tidak dinilai paksa.
3. **Kandidat awal:** skor kualitas teks tinggi + market value rendah.
4. **Validasi angka:** rating per posisi (z-score, tertimbang menit) dan stat per 90 harus di atas median posisinya.
5. **Hidden gem flag** dihitung sebagai turunan murah dari tiga persentil yang sudah ada (kualitas, buzz, harga). Bila waktu tidak cukup, dilaporkan sebagai narasi di laporan, bukan kolom dataset.
6. Filter kebutuhan klub (cocokkan playstyle/role, mis. "deep-lying playmaker") **ditunda** ke future work.

### Tahap F — Output dan laporan

Lihat §10. Laporan ditulis mengikuti alur CRISP-DM (rincian di [`PLAN-1WEEK.md`](PLAN-1WEEK.md)).

## 8. Skema dataset

**players**

- `player_id`, `sofifa_id`, `transfermarkt_id`, `fotmob_id`
- `name_canonical`, `name_aliases` (list)
- `position`, `position_group` (GK/DEF/MID/FWD), `club`, `league`, `nationality`, `birth_date`
- `playstyles` (list, opsional), `roles` (list, opsional)
- `in_text_sample` (bool) — menandai pemain yang masuk jalur teks

**texts**

- `text_id`, `player_id`, `source` (reddit/youtube/article)
- `text_raw`, `text_clean`, `language`
- `created_at`, `url` / `thread_id`, `engagement` (opsional)
- `unit_type` (comment/sentence/transcript_segment) — wajib, karena analisis berjalan di level kalimat

**text_analysis**

- `text_id`, `player_id`, `sentiment_label`, `sentiment_score`
- `aspect`, `aspect_sentiment`
- `is_aspect_bearing` (bool) — kalimat tanpa kata kunci aspek

**metrics_numeric**

- `player_id`, `season`, `minutes`, `avg_rating`, `rating_std`
- `xg_per90`, `xa_per90` (opsional), `market_value_eur`

**player_summary**

- `player_id`, `season`, `n_texts`, `evidence_level` (cukup/terbatas/tidak cukup)
- `text_quality_score`, `top_aspects`, `buzz_volume`, `buzz_percentile`
- `rating_pos_zscore`, `market_value_eur`, `value_percentile`
- `undervalued_flag`, `hidden_gem_flag` (opsional), `overhyped_flag`

## 9. Definisi inti

| Istilah | Definisi |
|---|---|
| **Skor Kualitas Teks** | Rata-rata tertimbang sentiment aspek relevan posisi, rentang −1 sampai 1 |
| **Buzz** | Jumlah teks valid per pemain, dinormalisasi terhadap total populasi |
| **Performa (validator)** | Rating tertimbang menit, diubah ke z-score di dalam posisinya |
| **Biaya** | Market value Transfermarkt |
| **Undervalued** | Skor kualitas teks ≥ persentil 75 di posisinya, market value ≤ persentil 40, dan performa angka di atas median posisinya |
| **Hidden gem** | Undervalued dengan buzz ≤ persentil 40 |
| **Overhyped** *(sekunder)* | Buzz ≥ persentil 75 dan performa di bawah median posisinya |

**Catatan definisi untuk konteks Premier League**

- Persentil market value dan persentil performa dihitung **di dalam Premier League, per posisi** — bukan batas harga absolut.
- "Hidden gem" di Premier League dibaca sebagai **underrated** (diremehkan publik atau pasar), bukan pemain tak dikenal. Ini masuk bagian keterbatasan laporan.
- Populasi per posisi kecil (puluhan pemain), sehingga persentil tidak stabil di ekornya. Laporkan **peringkat** dan **interval kepercayaan bootstrap**, jangan hanya satu angka persentil.
- Ambang persentil adalah nilai awal dan boleh disesuaikan setelah eksplorasi. Setiap perubahan dicatat beserta alasannya (lihat §17).

## 10. Output

- **[1 minggu]** Tabel top 10–20 kandidat undervalued: skor kualitas teks, market value, rating tervalidasi, aspek unggulan, `evidence_level`.
- **[1 minggu]** Scatter plot: skor kualitas teks vs market value, warna = rating z-score, ukuran = buzz.
- **[1 minggu]** Heatmap sentiment aspek per posisi.
- **[1 minggu]** Analisis pendukung: korelasi buzz vs market value, daftar overhyped (avoid list).
- **[1 minggu]** Laporan temuan dan keterbatasan.
- Bonus, bukan syarat: kolom playstyle pada tabel kandidat, dashboard Streamlit (tabel filter per posisi, scatter, detail per pemain).

**Batas kelayakan minimum di akhir minggu:** dataset teks bersih, bukti entity linking dan sentiment dievaluasi manual, satu tabel kandidat dengan validasi angka, dan 3–4 visual. Kalau dashboard belum siap di Hari 6, cukup notebook dengan visual rapi.

## 11. Metrik keberhasilan

| Metrik | Target 1 minggu | Cara ukur |
|---|---|---|
| Entity linking benar | ≥ 85% pada sampel manual | 100 teks berlabel oleh 4 orang |
| Relevansi retrieval (teks memang membahas pemain itu) | ≥ 85% | 100 teks acak dari hasil scraping, dicek manual |
| Akurasi sentiment | ≥ 75% pada 100 teks berlabel manual | Bandingkan label model vs label manual |
| Kesepakatan antar-anotator | Cohen's κ dilaporkan apa adanya | 12 teks overlap dilabeli keempat orang |
| Kecukupan bukti per pemain | Lihat batas bertingkat di bawah | Hitung `n_texts` |
| **Metrik bukti utama** | Persentase kandidat dari teks yang juga di atas median rating posisinya — dilaporkan; ≥ 60% dibaca sebagai sinyal teks berguna, di bawah itu ditulis sebagai temuan negatif | Gabung `player_summary` |
| Reproducibility | Satu perintah dari data mentah ke output | `make pipeline` atau satu skrip |

**Batas kecukupan teks (Premier League — teks melimpah, jadi batas lebih tinggi daripada liga kecil):**

- **≥ 30 teks** → `bukti cukup`, dinilai penuh, boleh masuk tabel kandidat.
- **10–29 teks** → `bukti terbatas`, boleh tampil tapi wajib bertanda dan tidak masuk peringkat utama.
- **< 10 teks** → `bukti tidak cukup`, tidak dinilai, tidak masuk tabel kandidat.

Seluruh angka target pada tabel ini adalah usulan awal; kalau di Hari 4 ternyata tidak realistis, turunkan targetnya dan catat alasannya — jangan hapus metriknya.

## 12. Risiko dan mitigasi

| Risiko | Mitigasi |
|---|---|
| Akses Reddit macet (persetujuan API lama) | Keputusan di Hari 1; jika gagal, YouTube + artikel jadi sumber utama dan laporan menyebutnya |
| Market value Premier League tinggi dan semua pemain sudah diawasi | Pakai persentil di dalam liga per posisi, bukan batas harga absolut; framing sebagai *underrated* |
| Pemain di sampel teks sedikit dibicarakan | Buzz rendah jadi fitur; label `bukti terbatas` / `bukti tidak cukup`; prioritaskan transkrip dan subreddit klub |
| Bias volume (bintang mendominasi) | Kuota teks per pemain per sumber; normalisasi buzz terhadap populasi; sampling berlapis per kuartil harga |
| Salah sasaran (nama ambigu, thread multi-pemain) | Pecah per kalimat sebelum linking; disambiguasi konteks klub; pilot 20 pemain sebelum scraping penuh |
| Sarkasme dan slang bola merusak sentiment | Sampel evaluasi manual, catat contoh kegagalan di laporan, tambah kamus slang bila perlu |
| Sentiment mengikuti hasil laga terakhir | Agregasi per periode, bukan per laga; laporkan distribusi bukan hanya rata-rata |
| Kuota YouTube API habis | Pakai `playlistItems.list`, bukan `search.list`; cache hasil; hitung kuota sebelum jalan |
| Rating beda antar sumber | Satu sumber rating saja; normalisasi per posisi; mulai satu liga |
| ToS dan blokir IP | Rate limit, cache, cek `robots.txt`, hanya data publik |
| Sampel teks dianggap cherry-picked | Sampel dikunci Hari 1 sebelum scraping, dicatat di laporan sebagai sampel acak berlapis |
| Hasil belum tentu berlaku di liga lain | Ditulis sebagai keterbatasan; uji ekspansi di tahap lanjutan |
| Dosen menilai teks hanya "ditempel" | Teks menentukan skor utama dan kandidat, angka hanya harga dan validator; urutan pipeline di laporan dibuat eksplisit |

## 13. Etika dan legalitas

- Patuhi `robots.txt` dan ToS; hanya untuk keperluan akademik dan portfolio.
- Anonimkan username penulis komentar — tidak menyimpan username maupun data pribadi.
- Jangan redistribusi data mentah; yang dibagikan hanya agregat dan kode.
- Jangan menembus paywall.

## 14. Jadwal 7 hari

| Hari | Target |
|---|---|
| 1 | Kunci skema tabel (`players`, `texts`), daftar sampel 60–80 pemain, keputusan Reddit/YouTube, config liga, setup repo. Daftar pemain dikirim sebelum malam |
| 2 | Scraping jalan untuk 20 pemain (pilot) dari campuran bintang dan non-bintang. Cek manual 100 teks acak: apakah benar membahas pemain itu |
| 3 | Perbaiki filter dari hasil pilot, scraping penuh 60–80 pemain. Entity linking dan sentiment mulai dikerjakan di data yang sudah masuk |
| 4 | Scraping dan cleaning selesai. Aspek dan Skor Kualitas Teks jadi. Labeling manual 100 teks |
| 5 | Join dengan market value dan rating, validasi angka, kandidat undervalued. Hitung akurasi sentiment |
| 6 | Visualisasi (scatter, heatmap aspek per posisi, tabel top 10–20) dan penulisan laporan |
| 7 | Buffer: perbaiki, rapikan, latihan presentasi. **Jangan tambah fitur baru** |

Dua titik rawan: **Hari 1** (kalau skema telat, semua tertahan) dan **Hari 3** (kalau scraping baru jalan di Hari 4, jadwal geser dan Hari 6 jadi sempit).

Jadwal lengkap dengan pembagian peran ada di [`PLAN-1WEEK.md`](PLAN-1WEEK.md).

## 15. Stack

Python, pandas, `requests`/Playwright, `soccerdata`, PRAW, YouTube Data API v3, `youtube-transcript-api`, `trafilatura`, `rapidfuzz`, spaCy, Hugging Face Transformers (termasuk VADER), scikit-learn, matplotlib/plotly, SQLite/Parquet. Streamlit opsional.

Prinsip: satu config untuk liga dan musim, cache di disk, data mentah terpisah dari data bersih.

## 16. Keputusan terbuka

1. **Porsi kolom numerik** yang diizinkan dosen agar dataset tetap "dominan string" — perlu ditanyakan ke dosen. Sampai ada jawaban, kolom numerik dijaga minimum: menit main, market value, rating, xG/xA per 90.
2. **Akses X/Twitter**: dicoba atau dilewati? Default: **dilewati**, Reddit dan YouTube jadi sumber utama.

*Sudah diputuskan:* liga = Premier League 2025/26, musim = 2025/26, bahasa = Inggris saja, filter harga di tahap populasi = mati.

## 17. Panduan untuk AI agent

Akan dipindahkan ke `AGENTS.md` di root repo pada Hari 1, setelah struktur folder jadi. Untuk sekarang aturannya hidup di sini.

- Populasi pemain selalu berasal dari data terstruktur, bukan dari teks.
- Scraping selalu player-centric: query per pemain dengan batas tanggal dan sumber whitelist.
- Pecah teks per komentar/kalimat sebelum entity linking; jangan melabeli satu thread ke satu pemain.
- Simpan data mentah terpisah dari data bersih; jangan menimpa data mentah.
- Semua scraper wajib: rate limit, retry dengan backoff, caching, User-Agent wajar.
- Gunakan `player_id` internal sebagai satu-satunya kunci join.
- Jangan memakai value/wage SoFIFA sebagai target harga.
- Pemain di bawah batas minimal teks diberi label "bukti tidak cukup", jangan dinilai paksa.
- Evaluasi sentiment dan entity linking dengan sampel berlabel manual sebelum dipakai di analisis.
- Catat setiap perubahan ambang persentil beserta alasannya, di `docs/decisions.md`.
- Jangan menyimpan username atau data pribadi penulis komentar.
- Patuhi `robots.txt`/ToS; jangan menembus paywall.
- Konfigurasi liga dan musim disimpan di satu file config (`league=EPL`, `season=2025/26`); jangan hardcode di kode scraper.
- Daftar subreddit klub, channel YouTube, dan situs artikel disimpan sebagai whitelist di config.
- Daftar sampel pemain dikunci sebagai file di `data/processed/`, bukan dihasilkan ulang setiap kali skrip jalan.

## 18. Riwayat revisi

| Versi | Perubahan |
|---|---|
| 1.0 | Draf awal: multi-liga, 3–4 sumber teks, ±200 pemain, aspect-based sentiment berbasis model, BERTopic, filter kebutuhan klub |
| 1.1 | Liga dikunci sebagai parameter; prototipe dipersempit ke satu liga; X ditandai opsional |
| 2.0 | Liga = Premier League 2025/26. Scope dipangkas untuk 4 orang × 1 minggu: 2 sumber teks utama, populasi teks ±60–80 pemain (sampling berlapis), sentiment model siap pakai + aspek berbasis kamus, batas kecukupan teks bertingkat, BERTopic dan filter playstyle ditunda |
