# Tahap B — YouTube (komentar kanal whitelist)

Status: **kolektor komentar selesai dan sudah dijalankan penuh untuk 70 pemain.**
Dedupe silang dengan Reddit juga sudah selesai (0 duplikat; lihat bagian Dedupe).
Transkrip video **belum** diambil meskipun `include_transcript: true` ada di config.

Dokumen ini menjelaskan apa yang diambil, keputusan yang diambil beserta angkanya,
dan keterbatasan yang wajib masuk laporan. Semua angka di sini berasal dari
`data/raw/youtube/full-*/summary.json` dan skrip di `src/scrape/youtube.py`.

## Peran di Tahap B

YouTube adalah sumber teks **kedua** setelah Reddit, bukan pengganti. Pembagiannya:

| Peran | Isi |
|---|---|
| Teks → sinyal kualitas | komentar YouTube + Reddit, diproses D |
| Angka → harga & validator | market value + rating FotMob (A, D) |
| Populasi | dari data terstruktur A, **tidak pernah** dari YouTube (aturan 1) |

Yang diambil hanya teks, bukan angka. Tidak ada metrik performa dari YouTube yang
dipakai, dan tidak ada pemain yang ditambahkan ke populasi karena muncul di video.

## Sumber teks

Lima kanal, semuanya sudah diverifikasi lewat `channels.list?forHandle=` pada
2026-11-12. Handle dan ID disimpan di `config/config.yaml` (bukan di cache
`data/raw/`, yang gitignored) supaya hasil bisa direproduksi dari clone bersih.

| Kanal | Handle | Video dalam musim |
|---|---|---|
| The Overlap | `@TheOverlap` | 973 |
| Tifo Football | `@TIFO` | 287 |
| The Athletic FC | `@TheAthleticFC` | 317 |
| Sky Sports Premier League | `@SkySportsPremierLeague` | 2.075 |
| Premier League | `@premierleague` | 1.329 |
| **Total** | | **4.981** |

Dua nama di `config.yaml` sengaja berbeda dari tebakan awal, dan keduanya adalah
kesalahan yang **tidak memunculkan error**:

- `@TifoFootball` tidak ada. Kanalnya sekarang `@TIFO`, berjudul "Tifo Football by
  The Athletic" — sudah bergabung dengan The Athletic, jadi isi kedua kanal bisa
  tumpang tindih.
- `@SkySportsPL` **ada**, tetapi itu kanal penggemar "TRS SkySports", bukan Sky
  Sports. Handle yang salah tetap mengembalikan hasil sukses; yang membongkarnya
  hanya pemeriksaan judul kanal.

Karena itu `channel_sources()` memeriksa kecocokan judul dan menulis peringatan
bila judul kanal tidak cocok dengan nama di config.

## Alur

1. **Resolusi kanal** — dari `uploads` di config; `handle` hanya dipakai bila
   `uploads` belum ada. Kegagalan di sini berhenti keras, bukan dilewati diam-diam.
2. **Scan uploads sekali per kanal** — bukan per pemain. Uploads urut terbaru →
   terlama, jadi penyusuran berhenti begitu satu halaman sudah lebih tua dari
   `league.season_start`. Jendela musim dibaca dari config, tidak ada tanggal di kode.
3. **Pencocokan per pemain** — judul dulu, deskripsi hanya bila judul meleset.
4. **Ambil komentar** per video kandidat, maksimal 2 halaman (200 komentar teratas).
5. **Saring per komentar** — panjang minimum, bahasa Inggris, bukan bot, di dalam
   jendela musim, belum pernah muncul (`text_clean_hash`), dan nama pemain benar
   menurut `AliasIndex` + aturan 17.
6. **Tulis** — `data/raw/youtube/<tag>-<timestamp>/` (tidak pernah ditimpa),
   `data/interim/texts_youtube_<tag>.jsonl`, dan `summary.json`.

## Keputusan desain

Semua sudah tercatat dengan tanggal di [`decisions.md`](decisions.md). Ringkasnya:

| Keputusan | Alasan |
|---|---|
| Indeks video dibangun **sekali per kanal**, bukan per pemain | `search.list` = 100 unit dan dilarang. Membaca ulang uploads per pemain ≈ 70 × 40 = 2.800 request, melampaui kuota harian 10.000. Sekali baca: ~150 unit untuk 4.981 video |
| `playlistItems.list`, **bukan** `search.list` | Aturan repo; biaya 1 unit vs 100 unit per panggilan |
| Deskripsi ikut dicocokkan | Diukur pada 3 kanal: judul saja menyebut 47 dari 70 pemain, judul-atau-deskripsi 59. Menutup 12 pemain |
| Konteks video menggantikan konteks subreddit | Komentar YouTube tidak punya subreddit. Tanpa ini setiap sebutan marga ("Saka was clinical") gugur di aturan 17 |
| Identitas komentator dibuang **sebelum** cache ditulis | Aturan 11. Payload `commentThreads` membawa `authorDisplayName`/`authorChannelId`; kalau cache ditulis lebih dulu, username masuk ke disk |
| `max_texts_per_player` menghitung **komentar**, bukan komentar + kalimat | Versi pertama menghitung keduanya, sehingga cap 40 tercapai di 20 komentar. Setelah diperbaiki: 152 → 231 komentar pada pilot 20 pemain (+52%) |

## Angka terukur (2026-11-13)

| Angka | Nilai |
|---|---|
| Pemain diproses | 69 dari 70 (satu dikecualikan, lihat keterbatasan #1) |
| Video dalam musim dipindai | 4.981 |
| Pemain punya ≥1 video kandidat | 59 dari 69 |
| Komentar disimpan | **1.054** |
| Kalimat disimpan | **1.105** |
| Request / unit kuota (run penuh pertama) | 310 / 310 |
| Request / unit kuota (pengulangan) | **0 / 0** — seluruhnya dari cache |

Sebaran kecukupan bukti (batas PRD §9: ≥30 cukup, 10–29 terbatas, <10 tidak cukup):

| Label | Jumlah |
|---|---|
| `bukti cukup` (≥30 komentar) | 21 |
| `bukti terbatas` (10–29) | 10 |
| `bukti tidak cukup` (<10) | 38 |
| — di antaranya 0 komentar | 19 |

17 pemain berhenti tepat di 40 komentar karena cap `max_texts_per_player`, jadi
volume sebenarnya lebih tinggi. Cap ini sengaja ada supaya pemain populer tidak
menenggelamkan sampel.

## Tabel cleaning (ke mana teks yang gugur)

Setiap penolakan dihitung di dalam `records_from_comment`, ditulis ke
`summary.json`, lalu dirender oleh `src/scrape/cleaning.py` menjadi
`reports/cleaning_youtube.md`. Angka di bawah berasal dari run
`full-20261113-025149`; tidak ada yang ditulis dari ingatan. Run ulang dari cache
menghasilkan file teks yang identik sampai byte terakhir
(`SHA256 4375CA08A8DEC4D7B08897AE888383B0DC15C1B731BBB1E400F3CC50986E854F`),
jadi penghitung ini tidak mengubah korpus.

Satuannya **pasangan (pemain, komentar)**, bukan komentar unik. Satu komentar
diperiksa sekali untuk setiap pemain yang namanya mungkin disebut, jadi
"diperiksa" jauh lebih besar dari 1.054 komentar yang disimpan.

| Filter | Dibuang | Porsi | Alasan |
|---|---|---|---|
| Terlalu pendek | 13.170 | 37,9% | kurang dari `min_words` kata |
| Bukan bahasa Inggris | 227 | 0,7% | deteksi bahasa |
| Bot / spam | 0 | 0,0% | penanda bot |
| Tanpa tanggal | 0 | 0,0% | `publishedAt` kosong atau tidak valid |
| Di luar musim | 288 | 0,8% | di luar `season_start`..`season_end` |
| Duplikat dalam satu pemain | 25 | 0,1% | `text_clean_hash` sudah dipakai |
| Nama tidak teratasi | 19.986 | 57,5% | aturan 17 / `AliasIndex` |
| **Diperiksa** | **34.750** | 100% | |
| **Lolos menjadi komentar** | **1.054** | 3,0% | |

Kalimat disaring terpisah setelah komentarnya lolos: **939** kalimat gugur
karena tidak lagi menyebut nama pemain, **1.105** lolos. Kalimat yang gugur
tidak membatalkan komentarnya.

Dua angka yang perlu dijelaskan sebelum dibaca sebagai masalah:

- **`nama tidak teratasi` 57,5%** bukan kegagalan retrieval. Komentar di bawah
  video "Saka masterclass" kebanyakan membahas pemain lain, wasit, atau taktik;
  aturan 17 menolak setiap sebutan yang tidak bisa dipastikan. Kalau filter ini
  dilonggarkan, yang naik bukan recall melainkan jumlah tautan salah.
- **`terlalu pendek` 37,9%** adalah harga `min_words`: komentar satu baris
  ("Saka 😍") tidak punya kalimat untuk dianalisis sentimennya.

Jumlah yang tidak terhitung adalah **0**, artinya setiap komentar yang diperiksa
masuk tepat satu keranjang.

Tabel ini **tidak berubah** saat teks Reddit dari B masuk — ia hanya menjelaskan
jalur YouTube.

### Sebaran kanal

Komentar yang lolos per kanal, di samping jumlah unggahan dalam musim dari kanal
itu:

| Kanal | Video dalam musim | Komentar | Porsi komentar |
|---|---|---|---|
| Sky Sports Premier League | 2.075 | 747 | 70,9% |
| The Athletic FC | 317 | 144 | 13,7% |
| Premier League | 1.329 | 104 | 9,9% |
| Tifo Football | 287 | 31 | 2,9% |
| The Overlap | 973 | 28 | 2,7% |
| **Total** | **4.981** | **1.054** | 100% |

Unggahan bukan satu-satunya penentu: The Overlap mengunggah 973 video tetapi
hanya menyumbang 28 komentar, sedangkan The Athletic 317 video menghasilkan 144
komentar. Yang menentukan adalah apakah video kanal itu menyebut pemain sampel
dan apakah komentarnya menyebut nama pemain itu. Konsekuensinya dibahas di
keterbatasan #5.

## Kuota dan cache

Kuota YouTube Data API 10.000 unit/hari, reset tengah malam waktu Pasifik. Total
pemakaian selama pengembangan (smoke test, pengukuran kanal, tiga pilot, dan run
penuh): **±640 unit**. Satu run penuh dari cache kosong ≈ 310 unit, jadi masih
aman dijalankan beberapa kali per hari.

Cache disimpan di `data/raw/youtube/cache/<endpoint>/<sha256[:32]>.json`. Nama file
sengaja pendek dan panjangnya tetap: nama yang dibangun dari parameter query akan
tumbuh mengikuti query dan menembus batas 260 karakter Windows (bug yang sama
sudah terjadi di `arctic_shift_client.py`).

## Gate relevansi (PRD §11)

Ini uji mutu retrieval, bukan anotasi dataset. Tujuannya memastikan teks yang
masuk memang membicarakan pemain yang benar.

```bash
# 1. tarik 100 komentar acak dari run pilot Hari 2 (seed tetap dari config)
make review N=100 SOURCE=youtube TAG=pilot20

# 2. isi kolom `relevant` dengan y/n di Excel, lalu
make review-score SOURCE=youtube
```

`TAG` penting: tanpa itu skrip mengambil file terbaru, yang setelah scraping penuh
bukan lagi data pilot. Gate Hari 2 diukur pada pilot sesuai
[`PLAN-1WEEK.md`](PLAN-1WEEK.md) §3, supaya filter diperbaiki **sebelum** scraping
penuh bila hasilnya di bawah target.

Hasilnya `reports/retrieval_relevance_youtube.md`, terpisah dari laporan Reddit.
Jalur Reddit tidak berubah sama sekali: nama sheet, nama laporan, dan angkanya
tetap seperti sebelumnya.

**Status: sheet sudah ditarik dari `texts_youtube_pilot20.jsonl` (231 komentar dari
12 pemain; run itu memproses 20 pemain dan 8 di antaranya tidak mendapat komentar
sama sekali), 100 baris, 10 pemain berbeda, belum dilabeli.** Pelabelan harus
dilakukan manusia — angka gate yang diisi sendiri oleh pembuat kode tidak sah.
Lembar ini tidak boleh ditarik ulang setelah ada label; skrip menolak dan meminta
lembar lama dipindahkan.

Satu catatan metodologis: sampel acak seragam atas komentar membuat pemain
bervolume besar mendominasi lembar (10 dari 12 pemain yang punya komentar). Gate
ini mengukur **presisi**, bukan cakupan. Karena itu gate pilot tidak boleh dibaca
sebagai gambaran pemerataan bukti antar pemain — untuk itu lihat tabel kecukupan
di atas.

**Urutan yang menyimpang dari AGENTS.md, dicatat terbuka.** Run penuh (1.054
komentar) sudah dijalankan sebelum lembar gate ini dilabeli, padahal aturannya
gate pilot dulu. Konsekuensinya: bila gate nanti di bawah 85%, filter harus
diperbaiki dan run penuh diulang. Biayanya kecil dan bukan permanen — seluruh
respons API sudah di cache, dan penyaringan terjadi setelah pengambilan, jadi run
ulang dengan filter yang berubah memakai 0 unit kuota. Yang tidak boleh terjadi
adalah menyatakan gate lulus tanpa label manusia.

## Keterbatasan yang wajib masuk laporan

### 1. Satu pemain dikecualikan karena teksnya milik orang lain

André (`fotmob_1174296`) dikecualikan dari jalur YouTube. Dari 40 komentar yang
cocok, **22 (55%) sebenarnya tentang Andre Silva**, adik Diogo Jota yang meninggal
di kecelakaan yang sama. Contoh nyata:

> "Rest In Peace Diogo Jota & Brother Andre Silva, YNWA"

Penyebabnya: alias satu kata `Andre` cocok sebagai **awalan** nama orang lain —
`find_mentions` mencari `" andre "` di dalam `" andre silva "`. Konteks klub tidak
menolong, karena video tribute itu memang menyebut Wolves (klub Jota dulu) dan
André pemain Wolves. Jadi aturan 17 lolos secara teknis tetapi salah orang.

Kasus ini ditemukan lewat gate relevansi, bukan ditebak. Pengecualiannya ada di
`config/config.yaml` (`exclude_players`) beserta alasannya, dan alasannya ikut
tertulis di `summary.json` setiap run. Teks Reddit André **tidak** terpengaruh.

Tiga varian perbaikan sudah diukur dan semuanya tidak bersih: menolak alias yang
diikuti kata berhuruf kapital menangkap 9 dari 22 kasus André Silva tetapi ikut
membuang 13 komentar sah ("Kerkez Gravenberch Mac Alister…"). Perbaikan yang benar
ada di `aliases.py` dan akan mengubah keluaran Reddit, jadi harus dibicarakan
dengan pemilik jalur Reddit. Sampai itu terjadi, kasus ini dilaporkan sebagai
keterbatasan, bukan ditambal diam-diam.

Bug yang sama berpotensi mengenai Reddit: komentar r/soccer tentang André Silva
juga akan terhitung sebagai André.

### 2. YouTube tidak bisa menutup seluruh sampel

19 pemain tidak mendapat satu komentar pun, dan penyebabnya dua hal berbeda:

**Tidak ada video yang menyebut mereka sama sekali (10 pemain):**
Kristoffer Ajer, Tyrick Mitchell, Jacob Bruun Larsen, David Brooks, Trai Hume, Sam
Johnstone, Lucas Perri, Mads Hermansen, Djordje Petrović, Youri Tielemans.

**Ada video kandidat, tetapi tidak ada komentar yang menyebut nama mereka (9
pemain):** Axel Tuanzebe, Antonee Robinson, Cristhian Mosquera, Rodrigo Gomes,
Marcus Edwards, Jørgen Strand Larsen, José Sá, Emiliano Martínez, Jackson
Tchatchoua.

Dua di antaranya punya sebab yang bisa dijelaskan dan bukan kegagalan kode:

- **Marcus Edwards** — video yang cocok ternyata tentang **Rob Edwards**, manajer
  Wolves. Penyaring tingkat komentar membuangnya dengan benar, jadi 0 komentar
  adalah hasil yang tepat, bukan kerugian.
- **Emiliano Martínez** — 6 komentar jelas tentangnya ("Emi Martinez saved 2")
  gugur karena `name_aliases` di data populasi tidak memuat julukan **"Emi
  Martinez"**. Ini kehilangan recall yang nyata, dan perbaikannya ada di file
  populasi (milik A), bukan di kolektor.
- **Rodrigo Gomes** — Wolves punya tiga pemain bernama Gomes (João, Rodrigo, Toti).
  Komentar menulis "Gomes" atau "Rodrigo" saja, yang menurut aturan 17 tidak cukup
  untuk dikaitkan. Ini perilaku yang benar, dengan konsekuensi recall lebih rendah.

Pola umumnya jelas: yang tidak terliput sebagian besar **kiper dan bek murah** —
justru profil yang dicari proyek ini. Reddit tetap sumber utama untuk mereka.

### 3. Hanya komentar top-level

Balasan komentar tidak diambil. Diskusi pemain sering terjadi di dalam balasan, jadi
angka 1.054 komentar adalah batas bawah. Menambah balasan berarti satu request per
thread dan biaya kuota yang jauh lebih besar.

### 4. Cap 40 komentar per pemain

17 pemain menyentuh cap. Untuk pemain populer, 40 komentar adalah sampel, bukan
seluruh volume. Ini disengaja agar distribusi tidak dikuasai pemain bintang, tetapi
harus disebut saat membandingkan jumlah bukti antar pemain.

### 5. Komposisi kanal tidak seimbang

Pada run penuh, **747 dari 1.054 komentar (70,9%)** berasal dari Sky Sports
Premier League; The Athletic FC 13,7%, Premier League 9,9%, Tifo Football 2,9%,
The Overlap 2,7%. Sky Sports memang mengunggah paling banyak (2.075 video dalam
musim), tetapi volume unggahan saja tidak menjelaskan komposisi ini: The Overlap
mengunggah 973 video dan hanya menyumbang 28 komentar, sementara The Athletic
317 video menyumbang 144. Yang menentukan adalah video mana yang menyebut pemain
sampel dan komentar mana yang menyebut namanya. Angka per kanal dihasilkan oleh
`src/scrape/cleaning.py` dari `summary.json` run itu, bukan hitungan manual. Ini
bias sumber yang perlu disebut, bukan sesuatu yang dinetralkan.

### 6. Tumpang tindih Tifo dan The Athletic

Tifo sekarang berada di bawah The Athletic, jadi video yang sama bisa muncul di dua
kanal. `text_clean_hash` mencegah teks yang identik dihitung dua kali, tetapi
komentar yang berbeda pada video yang sama tetap bisa masuk dua kali.

### 7. Transkrip belum diambil

`include_transcript: true` ada di config tetapi **belum diimplementasikan**. Jangan
melaporkan cakupan transkrip dari modul ini.

### 8. "Hidden gem" berarti *underrated*

Sesuai aturan bahasa: di Premier League, pemain yang dibicarakan bukan pemain tak
dikenal. Ini harus tertulis di bagian keterbatasan laporan.

## Dedupe silang dengan Reddit (Tahap C)

Skrip: `src/link/dedupe.py`. Laporan: `reports/dedupe.md`. Perintah:

```bash
make dedupe                         # default: tag full untuk kedua sumber
make dedupe REDDIT_TAG=partial26    # uji coba pada data yang sudah ada
```

Keluaran: `data/processed/texts_deduped.parquet` (17 kolom; `channel` dan
`video_id` kosong untuk baris Reddit). File masukan hanya dibaca, tidak ditimpa.

Cakupannya sengaja sempit, dan alasannya angka yang diukur pada file penuh:

| Aturan | Alasan |
|---|---|
| Kunci `(player_id, text_clean_hash)`, bukan hash saja | **330** hash di file Reddit penuh dipakai **lebih dari satu pemain** (53 pada pilot); menyatukan hash akan memutus tautan entitas yang benar |
| Komentar dibandingkan dengan komentar, kalimat dengan kalimat | **831** hash di Reddit dan **556** di YouTube dipakai komentar **dan** kalimatnya sendiri; dedupe naif akan menghapus unit yang dipakai analisis sentimen |
| Hanya antar sumber | duplikat komentar di dalam satu sumber sudah dibuang scraper; yang tersisa hanya kalimat identik di dua komentar berbeda, dan itu dilaporkan (7 pasang), bukan dibuang |

Bila duplikat ditemukan, baris Reddit dipertahankan dan salinan YouTube dibuang —
teksnya identik, jadi pilihan ini tidak mengubah sentimen.

**Hasil final** (`texts_reddit_full.jsonl` × `texts_youtube_full.jsonl`):
**0 duplikat silang** dari 3.442 komentar Reddit dan 1.054 komentar YouTube.
Keluaran 9.220 baris (7.061 Reddit + 2.159 YouTube), 68 pemain, 17 kolom.

Nol adalah temuan, bukan kegagalan: komentar di dua platform hampir tidak pernah
identik kata per kata. Nilai dedupe ini ada pada buktinya — bahwa cakupan yang
sempit itu tidak membuang apa pun yang sah — bukan pada jumlah yang dibuang.

Dua hal yang hanya terlihat setelah kedua sumber digabung:

- **2 dari 70 pemain tidak punya teks sama sekali** dari kedua sumber: Jacob
  Bruun Larsen dan Jørgen Strand Larsen. Keduanya harus berlabel `bukti tidak
  cukup` dan tidak masuk tabel kandidat (aturan 8).
- **7 pasang kalimat identik dalam satu pemain** (0,2% dari 3.619 kalimat
  Reddit) tetap ada. Itu kalimat yang sama di dua komentar berbeda; dedupe ini
  tidak menyentuh duplikat dalam satu sumber, jadi D perlu menyaringnya saat
  agregasi kalau tidak ingin bobotnya dihitung dua kali.

Setelah penggabungan, sebaran bukti menjadi 59 pemain `bukti cukup`, 4 `bukti
terbatas`, 5 `bukti tidak cukup` (2 di antaranya nol). Angka itu dihitung dari
`texts_deduped.parquet` dan menjadi milik D untuk dilaporkan, bukan angka di
dokumen ini.

## Serah terima ke D

`data/` gitignored, jadi file diserahkan langsung, bukan lewat git:
`data/processed/texts_deduped.parquet` (hasil gabungan Reddit × YouTube siap
pakai, 9.220 baris) dan `data/interim/texts_youtube_full.jsonl` (khusus
YouTube).

Bentuk record sama dengan Reddit karena `YouTubeTextRecord` mewarisi `TextRecord`:
15 kolom identik, ditambah 2 kolom YouTube.

| Kolom | YouTube | Catatan untuk D |
|---|---|---|
| `source` | `youtube` | pembeda sumber saat digabung |
| `subreddit` | `""` | kosong; kanal ada di `channel` |
| `channel` | nama kanal | kolom baru |
| `video_id` | id video | kolom baru; sama dengan `thread_id` |
| `thread_id` | id video | pengganti id post Reddit |
| `unit_type` | `comment` / `sentence` | sama seperti Reddit |
| `parent_text_id` | id komentar induk | menautkan kalimat ke komentar |
| `engagement` | jumlah like | bukan skor kualitas, jangan dipakai sebagai bobot |

Dua hal yang harus D tangani:

1. **Satu komentar bisa muncul untuk dua pemain.** Contoh nyata: satu komentar
   menyebut Gakpo *dan* Kerkez → dua baris dengan `text_id` **berbeda** (player_id
   ada di dalam id) tetapi `text_clean_hash` sama. Saat agregasi per pemain,
   dedupe di dalam satu pemain saja. Dedupe global atas hash akan membuang salah
   satu baris dan membuat komentar itu tidak dihitung untuk pemain kedua.
2. **Pemain dengan <10 komentar jangan dipaksa dinilai** (aturan 8). Daftar 19
   pemain tanpa teks ada di atas dan di `summary.json`.

## Yang belum dikerjakan

- Transkrip video (`include_transcript`).
- Balasan komentar.
- Perbaikan `aliases.py` untuk bug awalan nama — menunggu keputusan pemilik jalur
  Reddit karena mengubah angka mereka.

## Perintah

```bash
make scrape-youtube                  # seluruh sampel, penuh
make scrape-youtube PILOT=20         # 20 pemain tersebar menurut market value
make review N=100 SOURCE=youtube     # tarik 100 teks untuk gate relevansi
make review-score SOURCE=youtube     # skor lembar yang sudah dilabeli
make cleaning                        # render tabel cleaning dari run terbaru
make cleaning RUN=<nama-run>         # render dari run tertentu
make dedupe                          # gabung dengan Reddit, buang duplikat silang
```

Setara tanpa `make`:

```bash
.venv/Scripts/python.exe -m src.scrape.youtube --pilot 20
.venv/Scripts/python.exe -m src.scrape.run --sample --n-sample 100 --source youtube
.venv/Scripts/python.exe -m src.scrape.cleaning --run full-20261113-025149
```

Butuh `YOUTUBE_API_KEY` di `.env`. Kalau kosong, skrip berhenti dengan instruksi
pembuatan key, bukan mencoba scraping anonim.
