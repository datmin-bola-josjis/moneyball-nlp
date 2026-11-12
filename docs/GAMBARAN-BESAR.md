# Gambaran Besar dan Pembagian Peran

Dokumen ini adalah versi ringkas yang dibaca semua orang di Hari 1 sebelum menyentuh kode. Untuk detail teknis, lihat [`PRD.md`](PRD.md); untuk jadwal harian, lihat [`PLAN-1WEEK.md`](PLAN-1WEEK.md).

---

## 1. Gambaran besar

Inti proyeknya satu pertanyaan: **apakah omongan orang di internet bisa menemukan pemain bagus yang harganya masih murah?**

### Masalahnya

Klub kecil tidak punya uang untuk membeli pemain bintang. Mereka butuh cara lain menemukan pemain bagus sebelum harganya naik. Scout profesional itu mahal dan kapasitasnya terbatas. Padahal di Reddit, YouTube, dan artikel, sudah ada banyak orang yang membicarakan pemain — sebagian analisisnya serius dan menyebut hal spesifik ("umpan panjangnya luar biasa", "finishing-nya buruk", "tidak pernah berhenti berlari").

### Idenya

> **Teks membuktikan kualitas, angka membuktikan performa, harga menunjukkan peluangnya.**

Kalau ketiganya bertemu di satu pemain — dipuji secara spesifik, angkanya di atas rata-rata posisi, harganya masih rendah — itu kandidat yang layak dilirik.

### Alurnya lima langkah

**1. Bikin daftar pemain dulu, dari data resmi.**
Ambil semua pemain Premier League 2025/26 yang main ≥ 900 menit. Ini keputusan desain yang paling penting: kalau daftar pemain dicari dari teks, pemain yang jarang dibahas tidak akan pernah masuk daftar — padahal justru mereka kandidat utamanya. Populasi dari data terstruktur, penilaian dari teks.

**2. Cari teks untuk tiap pemain.**
Bukan "ambil semua teks lalu cari nama di dalamnya", tapi kebalikannya: satu pemain, cari namanya di Reddit dan YouTube. Teks dipecah per kalimat, jadi kalau satu thread membahas tiga pemain, tiap kalimat ditempelkan ke pemain yang benar.

**3. Nilai teksnya.**
Sentiment per kalimat, lalu dikelompokkan per aspek: finishing, passing, bertahan, stamina, dribbling. Hasilnya satu angka per pemain: **Skor Kualitas Teks** (rentang −1 sampai 1).

**4. Uji pakai angka.**
Pemain yang teksnya dipuji tapi harganya murah, dicek rating dan statistik per 90-nya. Kalau angkanya juga di atas median posisinya, kandidatnya kuat. Kalau teksnya memuji tapi angkanya biasa, itu justru temuan menarik — bukan error yang harus disembunyikan.

**5. Keluar hasilnya.**
Tabel kandidat, plus visualisasi: scatter skor teks vs harga, heatmap aspek per posisi, dan daftar "overhyped" untuk dihindari.

### Kenapa ini ada nilainya di mata dosen

Kalau cuma sentiment analysis biasa, itu dangkal. Yang membedakan: **setiap langkah punya bukti.**

- Entity linking dites manual, dilaporkan akurasinya.
- 100 teks dilabeli manual untuk mengukur akurasi sentiment.
- Tiap pemain diberi label seberapa cukup buktinya — bukan dinilai paksa dengan 3 kalimat.
- Klaim akhirnya bukan "model kami bagus", tapi "inilah akurasi model kami, ini kesalahannya, ini keterbatasannya".

Itu yang membedakan tugas data mining yang dinilai prosesnya dari tugas yang cuma menempelkan hasil.

### Cakapan yang dipangkas untuk satu minggu

| Versi penuh | Yang dikerjakan sekarang |
|---|---|
| 3 sumber teks + X | 2 sumber: Reddit dan YouTube (artikel scouting bonus) |
| Seluruh populasi liga dapat teks | Data angka 20 klub penuh, teks hanya ±70 pemain |
| Aspect-based sentiment dengan model terlatih | Sentiment pakai VADER, aspek pakai kamus kata kunci |
| BERTopic, filter playstyle klub | Ditunda ke future work |

---

## 2. Pembagian peran

Empat orang. Kuncinya bukan sekadar "siapa mengerjakan apa", tapi **kapan tiap orang berhenti** — karena itu yang menentukan apakah pipeline dan laporan selesai bersamaan.

### A — Data populasi dan angka

**Paling awal jalan dan paling akhir selesai.**

Hari 1–3: bikin daftar pemain. Tarik roster 20 klub lewat `soccerdata`, hitung menit main, buat `player_id` internal, dan kumpulkan alias nama (dengan/tanpa aksen, nama pendek, julukan).

Alias ini kelihatan sepele tapi krusial. Tanpa "Bruno G." dan "Bruno Guimarães" masuk sebagai alias, scraper akan kehilangan teks tanpa error apa pun. Dia juga yang menentukan sampel 70 pemain dan menyimpannya sebagai file terkunci.

Hari 5–6: tarik angka sebagai validator — rating per laga, statistik per 90, xG/xA, market value. Lalu hitung z-score per posisi dan bikin visualisasinya.

**Yang bikin dia macet:** sumber rating campur-campur. Kalau sebagian dari FotMob dan sebagian dari FBref, z-score-nya tidak bisa dibandingkan. Pilih satu sumber untuk seluruh proyek.

### B — Scraper Reddit

**Kerja paling banyak di Hari 2–4.**

Query tiap pemain di r/soccer, r/PremierLeague, dan 20 subreddit klub, dibatasi tanggal musim 2025/26. Yang diambil bukan thread-nya, tapi komentarnya, lalu dipecah lagi per kalimat. Dia juga yang membuat logika dedupe dan filter: buang spam, buang komentar di bawah 8 kata, buang yang bukan bahasa Inggris.

Setelah scraping selesai: labeling manual 25 teks, dan menulis bagian metodologi laporan.

**Yang bikin dia macet:** akses API Reddit. Hari 1 harus sudah pasti bisa atau tidak. Kalau tidak bisa, pivot ke YouTube dan artikel malam itu juga — jangan ditunda ke Hari 3.

### C — Scraper YouTube dan artikel

**Sumber kedua, dengan pekerjaan paling teknis di sisi retrieval.**

YouTube: ambil video dari channel whitelist lewat `playlistItems.list`, bukan `search.list` — yang terakhir mahal dan kuota harian bisa habis dalam beberapa query saja. Filter video yang judulnya menyebut nama pemain, ambil komentarnya, plus transkripnya kalau sempat.

Transkrip adalah sumber bukti paling kaya karena isinya analisis, bukan cuma reaksi. Tapi juga paling mahal waktunya. Jadi statusnya bonus, bukan syarat.

Artikel: ambil URL dari sitemap/RSS situs whitelist, ekstrak dengan `trafilatura`, masuk kalau nama pemain muncul di judul atau ≥ 3 kali di isi. Tidak menembus paywall.

Setelah scraping: cleaning, dedupe silang terhadap hasil Reddit, dan labeling manual 25 teks.

### D — NLP dan skoring

**Memegang otak pipeline dan struktur repo.**

Entity linking untuk memastikan satu kalimat benar-benar membahas pemain itu dan bukan pemain lain dengan nama mirip. Sentiment pakai VADER, pengelompokan aspek pakai kamus kata kunci. Dia juga yang merancang formula **Skor Kualitas Teks** — bagaimana menggabungkan sentiment dengan jumlah teks, dan bagaimana menangani pemain yang cuma punya lima teks.

Di akhir: menggabungkan semuanya jadi tabel `player_summary` dan kandidat undervalued.

**Yang bikin dia macet:** kalau dia baru mulai Hari 4, dia kehabisan waktu. Hari 3 dia sudah harus bekerja di data yang sudah masuk, dengan skema tabel yang sudah fix.

---

## 3. Soal pembagian ini

Tiga orang pertama punya pekerjaan yang **berhenti di suatu titik**:

| Orang | Puncak beban | Berhenti di | Setelah itu mengerjakan |
|---|---|---|---|
| A | Hari 1–3 (populasi) dan Hari 5–6 (angka) | Hari 6 | — |
| B | Hari 2–4 (scraping Reddit) | Hari 4 | labeling, validasi, metodologi laporan |
| C | Hari 2–4 (scraping YouTube) | Hari 4 | labeling, validasi, visualisasi |
| D | Hari 3–5 (NLP + skoring) | Hari 5 | menulis bagian pemodelan |

D jalan paling akhir dan paling sempit waktunya.

Artinya: **jangan biarkan D sendirian di Hari 5–6.** Setelah B dan C selesai scraping, mereka harus langsung ambil bagian validasi, labeling, dan visualisasi — bukan menunggu D selesai lebih dulu. Kalau D jadi satu-satunya yang menulis kode di paruh akhir minggu, pipeline-nya akan jalan tapi laporannya bolong.

Dan satu aturan yang tidak boleh dilanggar: **semua orang ikut labeling.** Labeling bukan pekerjaan satu orang. Kalau ditumpuk ke D, Hari 4 akan macet dan Hari 5 kehilangan bahan.
