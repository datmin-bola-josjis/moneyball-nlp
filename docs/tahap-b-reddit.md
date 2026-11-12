# Tahap B — Akses Reddit (permohonan manual)

Status: **terbuka, tenggat Hari 1.** Permohonan **belum dikirim**; formulir siap
diisi (jawaban lengkap di bawah). Sampai disetujui, `.env` tidak bisa diisi dan
`make scrape` tidak bisa jalan — itu memang disengaja.

Ini risiko nomor satu di [`PLAN-1WEEK.md`](PLAN-1WEEK.md) §6 dan sudah disebut di PRD §12: "Akses Reddit macet (persetujuan API lama)".

## Masalahnya

Sejak November 2025 Reddit menutup pembuatan aplikasi mandiri. Membuka <https://www.reddit.com/prefs/apps> lalu menekan "create app" tidak lagi memunculkan form; yang muncul tombol yang mengarah ke:

> "In order to create an application or use our API you can read our full policies here: …/Responsible-Builder-Policy"

Sumber: [Reddit for Developers FAQ](https://developers.reddit.com/docs/guides/faq) — script/bot eksternal harus lewat Data API, dan "Access requires approval under the Responsible Builder Policy". Tidak ada jumlah percobaan ulang yang mengubah ini.

Konsekuensi untuk proyek: `REDDIT_CLIENT_ID` dan `REDDIT_CLIENT_SECRET` **tidak bisa** diperoleh hari ini. Kode Tahap B tetap jalan begitu kredensial ada; tidak ada perubahan kode yang dibutuhkan untuk mengakomodasi proses baru ini.

## Yang harus dilakukan (Hari 1, malam ini)

Kirim satu tiket lewat formulir resmi:

<https://support.reddithelp.com/hc/en-us/requests/new?tf_42139884615700=api_request_type_developer_clone&ticket_form_id=14868593862164>

Pilih jenis **Developer**. Jangan pilih *Researcher* (menuntut afiliasi universitas resmi + dokumen etik/IRB yang tidak ada dalam 1 minggu) dan jangan *Enterprise* (kontrak berbayar).

### Jawaban yang diisi

Isi apa adanya — jangan mengarang. Kalau ada yang tidak sesuai kenyataan, ubah kalimatnya, jangan ubah faktanya.

**App name**
```
moneyball-nlp
```

**Use case description** (field yang menentukan; sebut apa, bagaimana, di mana)
```
moneyball-nlp is a one-week university coursework project (Data Mining, semester 5,
team of four). It reads public posts and comments from a fixed whitelist of Premier
League subreddits to measure how players are discussed in text, then compares that
signal against public performance and market-value data. Strictly read-only: it
never posts, comments, votes, messages, or moderates.

Access is used to search posts and read comment threads for a fixed list of about
70 players, each query scoped to one player name, one subreddit, and a fixed date
window (1 July 2025 - 31 May 2026). Comments are split into sentences for
sentiment analysis. Comment author usernames are never stored or published; only
aggregate per-player statistics appear in the coursework report. Raw text is not
redistributed - only aggregates and the analysis code are shared with the course
instructor. No model training on Reddit content, no commercial use, no resale.
```

**Data / API actions requested** (batasi ke read-only; jangan minta lebih)
```
Read-only: subreddit metadata (about), search posts within a subreddit (search),
and comment listings (comments). No write actions.
OAuth scope: read.
```

**Subreddits you will access**
```
r/soccer, r/PremierLeague plus the club subreddits of the 20 Premier League clubs 2025/26:
r/Gunners,
r/avfc,
r/AFCBournemouth,
r/Brentford,
r/BrightonHoveAlbion,
r/Burnley,
r/chelseafc,
r/crystalpalace,
r/Everton,
r/fulhamfc,
r/LeedsUnited,
r/LiverpoolFC,
r/MCFC,
r/reddevils,
r/NUFC,
r/nffc,
r/safc,
r/coys,
r/Hammers,
r/WWFC.
No other subreddits.
```

**Expected request volume**
```
Low: about 4,600 requests total for the whole week, spaced at least one second
apart, with on-disk caching so repeated runs re-read local files instead of
calling the API again.
```

**Platform / app type**
```
Script app - personal, server-side, runs locally on my own machine. Not
distributed to other users.
```

**Redirect URI** (wajib diisi walau tidak dipakai)
```
http://localhost:8080
```

**Commercial use?**
```
No. Non-commercial university coursework. No monetization of any kind.
```

**Data deletion / retention**
```
Comment text is retained locally only for the duration of the coursework
(about one week) to compute per-player sentiment aggregates, then deleted.
Author usernames are never stored in the first place. Raw responses are cached
on a local disk only to avoid re-calling the API; nothing is redistributed or
republished publicly, and the cache is deleted with the coursework data.
Deleted or removed Reddit content is not retained: the scraper skips
[deleted]/[removed] comments at collection time and the cache is discarded
before the final aggregates are produced.
```

## Tiga alternatif yang beredar — tidak dipakai, ini alasannya

Banyak panduan menyarankan jalan pintas. Bedanya: yang pertama **diuji langsung**
pada 2026-11-12 dari mesin proyek ini; yang kedua dan ketiga **dibaca dari
dokumentasi resminya** dan tidak dijalankan (alasan tidak dijalankan ada di
bawah). Hasilnya:

### 1. Endpoint `.json` publik tanpa OAuth — **403, mati**

Yang diuji, tiga User-Agent berbeda (proyek, browser Chrome, gaya Reddit),
masing-masing dengan jeda 1 detik:

| URL | Hasil |
|---|---|
| `https://www.reddit.com/r/soccer/hot.json` | **403** |
| `https://www.reddit.com/r/soccer/about.json` | **403** |
| `https://www.reddit.com/r/PremierLeague/search.json?q=...` | **403** |
| `https://old.reddit.com/r/soccer/hot.json` | **403** |

Mengganti User-Agent tidak mengubah apa pun: yang memblokir bukan User-Agent,
melainkan ketiadaan token OAuth. Ini sesuai [Reddit Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki)
(update 11 Mei 2026), yang menulis dua hal:

> "Clients must authenticate with a registered OAuth token."
>
> "Traffic not using OAuth or login credentials will be blocked, and the default
> rate limit will not apply."

Dan soal User-Agent, aturannya justru tegas: *"NEVER lie about your User-Agent."*
Menyamar sebagai browser bukan sekadar tidak membantu, tapi melanggar ketentuan —
juga melanggar AGENTS.md ("cari jalan pintas" dilarang). Memalsukan UA dan tetap
kena 403 menunjukkan klaim "cukup header User-Agent kustom" tidak lagi berlaku.
Cara ini **tidak dipakai** dan tidak akan dipakai.

Catatan: jawaban 403 di halaman ini sempat dikira bukti "subreddit tidak ada" —
bukan. 403 adalah blokir anonim, seperti yang sudah dicatat di `config/config.yaml`.

### 2. Devvit — **bukan pengganti, dan tidak bisa dipakai untuk proyek ini**

Devvit memang menghapus kebutuhan client_id untuk *app yang berjalan di dalam
Reddit*. Tapi tiga syaratnya mematikan untuk kasus ini:

1. **App harus terpasang di subreddit yang kamu moderasi.** Perintah resminya:
   `npx devvit install <subreddit>` — "Install an app from the Apps directory to a
   subreddit that **you moderate**" ([Devvit CLI](https://developers.reddit.com/docs/guides/tools/devvit_cli)).
   Kami tidak memoderasi r/soccer, r/PremierLeague, atau 20 subreddit klub.
2. **Itu platform JS/TypeScript yang di-host Reddit**, bukan jalan untuk menarik
   data keluar ke pipeline Python. Devvit mengeksekusi kode *di dalam* Reddit.
3. **API-nya berlingkup subreddit tempat app terpasang.** `reddit.searchPosts()`
   tanpa `subredditName` memang mencari di `all` ([Reddit API Overview](https://developers.reddit.com/docs/capabilities/server/reddit-api)),
   tapi app tetap harus diinstal pada satu subreddit dulu, dan datanya harus
   dikeluarkan lewat endpoint app sendiri — satu lapisan tambahan yang tetap
   harus patuh kebijakan yang sama.

Satu hal yang benar dari saran itu: Devvit **tidak** butuh `prefs/apps`. Tapi
menggantikan kebutuhan client_id dengan kebutuhan hak moderator bukan kemajuan.

### 3. Actor pihak ketiga di marketplace (Apify dan sejenisnya) — **melanggar ToS**

Apify Store menjual banyak "Reddit Scraper". Yang paling besar:
`trudax/reddit-scraper-lite` ($3.40/1.000 hasil, 52,8 ribu pengguna, **22,3%
run sukses**) dan `automation-lab/reddit-scraper` ($1.15/1.000 post,
99,7% run sukses, tanpa login).

**Biayanya bukan masalah.** Untuk beban kerja kita — 70 pemain × 60 komentar
≈ 4.200 komentar + ±700 post ≈ **$4 di tier gratis**. Uang bukan alasan
menolaknya. Alasan sebenarnya ada tiga:

1. **Reddit melarangnya secara tegas.** [Reddit User Agreement §7](https://www.redditinc.com/policies/user-agreement-march-31-2026)
   (efektif 31 Maret 2026) masuk daftar "Things You Cannot Do":

   > "Access, search, or collect data from the Services by any means (automated or
   > otherwise) except as permitted in these Terms or in a separate agreement with
   > Reddit (we conditionally grant permission to crawl the Services in accordance
   > with the parameters set forth in our robots.txt file, but **scraping the
   > Services without Reddit's prior written consent is prohibited**)."

   Actor di marketplace bukan "separate agreement" antara kita dan Reddit. Kita
   tidak punya izin tertulis; membeli jasa perantara tidak menciptakan izin itu.
   Menyuruh pihak ketiga melanggar untuk kita tetap pelanggaran oleh kita.

2. **Actor-nya sendiri bergantung pada kredensial atau trik yang sama.** Yang
   paling populer justru **meminta cookie `reddit_session`** milik akun Reddit
   pribadi kita — artinya kita menyerahkan sesi login ke pihak ketiga dan
   aktivitas otomatis itu menempel ke akun kita. Yang lain mengaku membaca
   "public feeds" atau memakai "short-lived anonymous Chromium bootstrap" —
   yaitu menghindari OAuth, persis yang dilarang Wiki Data API ("Clients must
   authenticate with a registered OAuth token"). Reddit juga sudah menuntut
   penyedia jasa scraping: *Reddit, Inc. v. SerpAPI LLC*, No. 25-cv-8736
   (S.D.N.Y.), dengan klaim DMCA yang sebagian besar lolos motion to dismiss
   pada 31 Juli 2026. (Berkas di CourtListener bernama `reddit-v-seprapi.pdf`;
   "Seprapi" itu salah ketik di nama berkas, bukan nama perkara — kaption
   perkaranya "SERPAPI LLC".) Angka 22,3% run sukses pada actor terbesar adalah gejala
   blokir itu, bukan bug.

3. **Kualitas datanya bergantung pada jalur mana yang dipakai actor.** Jalur
   normal mengembalikan `parentId` dan `depth` (dengan `-1` kalau tidak diketahui),
   jadi skema lengkapnya **ada**. Tapi README actor sendiri menyatakan bahwa saat
   Reddit membatasi akses tanpa login, ia beralih ke "public feeds": di jalur
   cadangan itu `score`, `upvoteRatio`, dan `numComments` bernilai `0`, komentar
   kehilangan `depth` dan `parentId`, `subredditSubscribers` selalu `null`, dan
   `sourceCommentCount` bisa `null`. Setiap baris membawa `warnings`, dan
   `coverage` tetap *"unverified"* walau kursor habis.

   Konsekuensinya untuk proyek: kita tidak bisa tahu di muka jalur mana yang
   dipakai untuk pemain mana, dan metrik kelulusan kita adalah **relevansi
   retrieval ≥ 85% dan jumlah teks per pemain** (PRD §11). Baris dengan `score 0`
   yang sebenarnya "tidak diketahui" akan salah dibaca sebagai "skor rendah" kalau
   dipakai untuk buzz atau filter engagement. Karena itu `apify_reddit.py` tidak
   memakai `score` sebagai filter dan mencatat `source="reddit_apify"` per baris,
   sehingga laporan bisa menyebut provider mana yang menghasilkan teks mana.

   Catatan kejujuran metodologis: angka di laporan tetap harus bisa ditelusuri ke
   skrip di repo (AGENTS.md). Dengan jalur ini, dosen bisa menjalankan ulang
   skripnya, tapi tidak bisa mereproduksi dataset mentahnya tanpa akun Apify
   berbayar. Itu harus ditulis di bagian keterbatasan laporan.

**Kesimpulan:** jalan yang sah dan berfungsi hanya formulir Data API di bagian
awal dokumen ini (dikirim malam Hari 1). Ketiga alternatif di atas tidak dipakai
untuk jalur utama.

Jalur Actor di marketplace sudah ditolak; lihat §3 di atas. Kodenya tetap ada di
`src/scrape/apify_reddit.py` sebagai catatan teknis dan **tidak dijalankan**
(`text_sources.reddit.apify.enabled: false`).

## Jalur Arctic Shift (dipakai untuk tenggat ini)

Keputusan tim: teks Reddit diambil lewat arsip pihak ketiga **Arctic Shift**,
`https://arctic-shift.photon-reddit.com`, karena OAuth tidak tersedia (formulir
Data API belum dikirim, `REDDIT_CLIENT_ID`/`SECRET` kosong) dan actor Apify sudah
ditolak. Ini **melanggar** aturan AGENTS.md "jangan cari jalan pintas saat akses
Reddit bermasalah" dan PRD §13, dan pelanggaran itu diterima secara sadar dengan
catatan tertulis di [`decisions.md`](decisions.md) 2026-11-12. Tidak ada
kredensial yang dipakai: satu-satunya header adalah
`User-Agent: moneyball-nlp/0.1 (coursework)`.

Kode: `src/scrape/arctic_shift.py`. Perintah:

```bash
make scrape-arctic                    # 70 pemain sampel terkunci
make scrape-arctic PILOT=20           # pilot 20 pemain
```

### Endpoint yang dipakai

Hanya satu: `GET /api/comments/search`, dengan parameter

| Parameter | Nilai | Catatan |
|---|---|---|
| `subreddit` | subreddit klub pemain | bukan subreddit liga; lihat tabel di bawah |
| `body` | **satu kata** = token terakhir nama pemain | `sa`, `larsen`, `peters` |
| `after` | epoch detik awal musim | |
| `before` | epoch detik akhir musim, lalu `created_utc` terlama halaman sebelumnya | wajib ada di halaman pertama juga |
| `limit` | 100, turun ke 25 | tangga limit |
| `sort` | `desc` | |

`after` dan `before` dikirim sebagai **bilangan bulat epoch** — format yang
terbukti menyaring dengan benar di sini. Keduanya **wajib ada sejak halaman
pertama**: `sort=desc` mulai dari baris terbaru arsip, jadi `after` saja
mengembalikan baris di luar musim yang kemudian gugur di filter jendela. Itu
sebabnya pilot pertama (`--pilot 3`) memberi satu pemain 0 komentar: seluruh
halaman pertamanya berisi baris Oktober 2026, dan setelah `before` ditambahkan
pemain yang sama menghasilkan 89 komentar.

Catatan kejujuran: dokumentasi arsip menyatakan tanggal ISO juga diterima. Probe
ISO di sini dibalas 422, tetapi 422 pada arsip ini juga berarti beban server
(subreddit tak ada pun dijawab `200 []`), jadi probe itu **tidak** membuktikan
ISO ditolak. Yang dipakai adalah format yang benar-benar terverifikasi bekerja,
bukan klaim bahwa format lain tidak didukung.

### Endpoint yang **tidak** dipakai, dan alasannya

| Yang dicoba | Hasil terukur | Konsekuensi |
|---|---|---|
| `/api/posts/search?title=` | **selalu 422** | tidak ada jalur thread; hanya komentar |
| `subreddit=soccer`, `subreddit=PremierLeague` | **selalu 422** (limit 10/25/100, jendela 1 bulan) | diskusi r/soccer & r/PremierLeague tidak tercakup |
| `body=` frasa dua kata (`Kieran Trippier`) | **selalu 422** | hanya kata tunggal |
| `limit=100` untuk term jarang (`WWFC`/`tchatchoua`) | 422; `limit=25` → 200 | tangga limit 100 → 25 |
| Subreddit tidak ada (`BurnleyFC`) | `200 []` | 422 = beban server, **bukan** "tidak ada hasil" |

### Angka yang diukur (2026-11-12)

| Uji | Hasil |
|---|---|
| `limit=100` untuk term umum (`WWFC`/`gomes`, `Gunners`/`mosquera`, `safc`/`mukiele`) | 200, penuh 100 baris |
| Paginasi `before=<created_utc terlama>` | 100 baris baru, 0 overlap |
| Retry pada 422 | ~40% percobaan pertama gagal; sukses pada percobaan 1–3 |
| Presisi term | r/Burnley `Edwards` 34/35; term marga lain 100/100; `[deleted]` 0 |
| `body=` | mencocokkan **substring**, bukan kata utuh |
| `GET /api/subreddits/search?subreddit=Burnley` | 200, 8.991 subscriber → r/Burnley **valid** |

Dua konsekuensi yang sudah ditangani di kode: (a) sifat substring dinetralkan
oleh `find_mentions`/`resolves` di `_records_from_comment`, jadi tidak ada
validasi kata utuh terpisah; (b) setiap jawaban 200 **langsung** di-cache ke
`data/raw/reddit/arctic/cache/` dan cache tidak pernah ditimpa.

### Dua pemain dengan 0 komentar di pilot 20 — penyebabnya berbeda

| Pemain | Penyebab | Bukti |
|---|---|---|
| `Alisson Becker` | request gagal, **bukan** retrieval kosong | alias `Becker` ada; tidak satu pun halaman `r/LiverpoolFC` `body=becker` berhasil — 8/8 percobaan 422, tercatat `failed_requests: 1` |
| `Jacob Bruun Larsen` | alias tidak pernah cocok | 5 komentar mentah dari `r/Burnley`, **3** menulis "Bruun Larsen"; `name_aliases` terkunci hanya memuat nama lengkap + `Jacob Bruun L.` |

Sebab alias: `split_name()` memperlakukan token terakhir sebagai marga, jadi
`Larsen` dihasilkan tetapi frasa `Bruun Larsen` tidak. Karena `Larsen` juga milik
pemain lain di sampel, `drop_colliding_aliases()` membuangnya dari keduanya.
Sampel terkunci tidak disunting (aturan 14); ini dicatat sebagai keterbatasan
recall, bukan ditambal dengan mencocokkan token terakhir secara global — itu akan
mengaitkan `Gomes`/`Silva` ke pemain yang salah (aturan 17).

### Keterbatasan yang wajib masuk laporan

1. **Sumbernya arsip pihak ketiga, bukan Data API resmi Reddit.** Ini pelanggaran
   ToS yang diterima secara sadar (lihat `decisions.md`), bukan ketidaktahuan.
2. **Dataset mentah tidak dapat direproduksi dosen** tanpa akses ke arsip yang
   sama. Skripnya bisa dijalankan ulang, isi arsipnya bisa berubah.
3. **Recall nama majemuk lebih rendah.** Lihat tabel di atas: pemain dengan
   marga majemuk yang bertabrakan (`Bruun Larsen`, `Strand Larsen`) hanya cocok
   lewat nama lengkap, sehingga komentar yang menyebut "Bruun Larsen" saja
   terlewat. Ini mengurangi jumlah teks, bukan menggeser skornya.
4. **Cakupan hanya subreddit klub.** Diskusi r/soccer dan r/PremierLeague tidak
   masuk karena endpoint-nya menolak subreddit besar. Pemain yang dibahas netral
   di forum liga akan kekurangan teks, dan itu tampil sebagai
   `players_without_text`/`bukti tidak cukup`, bukan disembunyikan.

### Catatan privasi (aturan 11)

Payload arsip adalah objek komentar Reddit utuh: ~72 field, termasuk `author`,
`author_fullname`, `profile_img` (URL avatar), `link_author` (penulis post),
`approved_by`/`banned_by`/`mod_reason_by` (nama moderator) dan `author_flair_*`.
Blacklist field **gagal** — `profile_img` dan `link_author` sempat tertulis ke
disk pada pilot pertama. Karena itu `_annotate()` sekarang **whitelist**: hanya
`id`, `body`, `created_utc`, `subreddit`, `score`, `permalink`, `link_id`,
`stickied` yang disimpan, ditambah `_skip` (keputusan bot/deleted/stickied yang
diambil **sebelum** nama dibuang, karena `keep_comment` butuh `author`). Cache dan
`*.comments.json` sama-sama melewati `_annotate()` sebelum ditulis.

## Jalur Apify — **dinonaktifkan** (catatan, bukan jalur yang dipakai)

Keputusan tim 2026-11-12 sempat: risiko pelanggaran diterima, actor
`automation-lab/reddit-scraper` dipakai sebagai provider opsional. **Keputusan itu
dibatalkan di hari yang sama** setelah ditinjau ulang.

Alasan pembatalan, singkat: actor ini melanggar Reddit User Agreement §7 dan
PRD §13, sedangkan AGENTS.md mewajibkan patuh ToS dan melarang jalan pintas saat
akses Reddit bermasalah. Menyuruh pihak ketiga melanggar untuk kita tetap
pelanggaran oleh kita. `text_sources.reddit.apify.enabled` kini `false`.

Bagian di bawah dipertahankan sebagai catatan teknis: ia menjelaskan apa yang
sudah diukur (biaya, yield, jebakan skema), berguna kalau sumber teks legal
lainnya nanti butuh perbandingan. **Jangan dijalankan tanpa keputusan tim baru
yang tertulis di `docs/decisions.md`.**

### Data yang sempat didapat — dan kenapa tidak dipakai

Hasil pilot **tidak bisa dipakai Stage C**, karena tiga alasan yang harus
dibedakan dengan jelas:

1. **ID pemain tidak cocok.** Pilot memakai `p_bruno_g`, `p_burn`, `p_murphy`
   dari daftar yang saya susun sendiri. Sampel terkunci A memakai `fotmob_*`
   untuk 70 pemain. Irisannya **kosong**, jadi tidak ada satu pun baris pilot
   yang bisa di-join lewat `player_id` (aturan 4).
2. **Satuan tidak boleh dijumlahkan.** Tiap komentar disimpan dua kali: satu
   `unit_type=comment` dan satu atau lebih `unit_type=sentence`. Angka "76 unit"
   adalah comment + sentence, bukan 76 komentar unik. Komentar uniknya: **36**.
   Stage D menilai di level kalimat, stage B melaporkan volume per komentar -
   keduanya tidak boleh digabung menjadi satu angka.
3. **Volumenya jauh di bawah ambang.** Bahkan bagian yang bisa diselamatkan
   (payload `pilot25` yang memakai pemain asli) hanya menghasilkan **12 komentar
   dari 2 pemain** (Matz Sels 10, Bernd Leno 2). Itu `bukti terbatas`, dan dua
   pemain tidak cukup untuk apa pun.

| Direktori | Komentar | Kalimat | Status |
|---|---|---|---|
| `pilot1-...065249` | 0 | 0 | bug `searchQueries`, tidak ada hasil |
| `pilot1-...065343` | 3 | 4 | ID karangan |
| `pilot1-...065654` | 7 | 7 | ID karangan |
| `pilot1-...065753` | 13 | 15 | ID karangan |
| `pilot3-...064623` | 0 | 0 | bug `searchQueries` |
| `pilot3-...065449` | 5 | 5 | ID karangan |
| `pilot3-...065449` (ulang) | 8 | 9 | ID karangan |
| `pilot25-...074626` | 0 | 0 | run dihentikan di 4/25 |

Yang tersimpan murni untuk audit: **36 komentar + 40 kalimat** dari 3 pemain
karangan, plus 1.078 item mentah (sudah disanitasi dari username).

### Biaya yang sudah keluar (tidak terulang)

$0.8717 dari kredit gratis $5, sisa $4.128 — 6 run pilot yang selesai plus satu
run 25 pemain yang dihentikan di pemain ke-4. Semua berada di bawah
`data/raw/reddit/`, tidak ada yang ditimpa.

### Menyalakan

1. Isi `APIFY_TOKEN` di `.env` (token dari
   <https://console.apify.com/settings/integrations>). Tidak dipakai oleh jalur OAuth.
2. Nyalakan di `config/config.yaml`:

   ```yaml
   text_sources:
     reddit:
       apify:
         enabled: true
   ```

3. Cek biaya dulu, tanpa menjalankan apa pun. Perintah ini juga membaca sisa
   kredit dari API Apify, bukan dari asumsi:

   ```bash
   python -m src.scrape.run --provider apify --estimate-cost
   ```

4. Pilot kecil dulu (3 pemain), bukan langsung 70:

   ```bash
   python -m src.scrape.run --provider apify --pilot 3
   ```

### Kuota dan biaya

Harga pay-per-result tier gratis: $0.00115/post, $0.00075/komentar, $0.003/run.

Yang penting: **komentar ditagih per post**, bukan per pemain. Actor menarik
hingga `max_comments_per_post` dari *setiap* post yang ia kembalikan, jadi
biayanya = pemain × post × komentar per post. Setelan awal 5 post × 12 komentar
memberi kuota 60 teks per pemain (sesuai PRD) dengan estimasi:

Angka di bawah memakai setelan terukur (`max_posts_per_player: 15`), bukan
tebakan. Harga tier gratis: $0.003/run + $0.00115/post + $0.00075/komentar.

| Cakupan | Post | Komentar | Estimasi |
|---|---|---|---|
| pilot 3 pemain | 45 | 540 | **$0.47** |
| pilot 20 pemain | 300 | 3.600 | **$3.10** |
| sampel penuh 70 | 1.050 | 12.600 | **$10.87** |

**Kredit gratis Apify hanya $5 per siklus.** Pemakaian per 2026-11-12: **$0.627**,
sisa **$4.373**.

Rinciannya: 6 run pilot yang selesai ($0.510) + **$0.117 terbuang** saat satu run
25 pemain dihentikan. Run itu sempat tertinggal `RUNNING` di sisi Apify lalu
di-abort manual; sekarang `run_actor()` melakukan abort otomatis begitu proses
lokal dihentikan. Direktori mentah run yang gagal sudah dihapus, jadi tidak ada
sisa data setengah jadi yang bisa dikira hasil sah.

Artinya jalur ini hanya sanggup sekitar **25 pemain**, bukan 70 —
`max_cost_usd` di config disetel `4.0` dan script menolak jalan kalau estimasi
melebihi sisa kredit (dibaca langsung dari API, bukan diasumsikan).

**Hasil panen yang terukur** (15 post, `sort: top`, `timeFilter: year`):

- hanya **35%** item yang dikembalikan jatuh di dalam musim (207/585);
- 8/15 post dan 81 komentar in-season per pemain;
- tetapi hanya **~13 komentar per pemain** yang benar-benar menyebut pemain itu.

13 komentar menempatkan hampir semua pemain di **`bukti terbatas` (10-29)**, bukan
`bukti cukup` (>=30). Konsekuensinya harus ditulis di laporan: tabel kandidat
undervalued praktis kosong untuk ambang PRD §11.

`max_cost_usd` di config adalah pagar keras: kalau estimasi melewatinya, script
berhenti sebelum satu request pun dikirim. Menaikkan `maxCommentsPerPost` ke 100
(seperti contoh di README actor) akan meledakkan biaya ke puluhan dolar — jangan.

### Yang perlu ditulis di laporan

- Reddit diperoleh lewat actor pihak ketiga, bukan Data API resmi.
- `score`/`upvoteRatio` bisa `0` karena "tidak diketahui", bukan "rendah". Skrip
  karena itu **tidak** memakai `score` sebagai filter atau untuk buzz.
- Dataset mentah tidak bisa direproduksi dosen tanpa akun Apify berbayar; hanya
  skripnya yang bisa dijalankan ulang.

### Batasan teknis yang sudah ditangani kode

- Setiap baris diberi `source="reddit_apify"`, jadi asal-usul teks bisa
  dilaporkan per baris.
- `text_id` memuat `player_id`, jadi satu komentar yang menyebut dua pemain
  menghasilkan dua record berbeda tanpa tabrakan kunci join.
- Hanya teks yang benar-benar menyebut pemain yang disimpan (aturan 3), dan hanya
  di dalam jendela musim.
- Payload mentah actor disimpan per pemain di
  `data/raw/reddit/<tag>-<timestamp>/<player_id>.items.json` beserta
  `.input.json`-nya, tidak pernah ditimpa.
- Jumlah teks per pemain dicetak dan pemain tanpa teks disebut namanya.
- Filter yang sama dengan jalur OAuth, karena didefinisikan sekali di
  `AliasIndex.resolves` dan dipakai kedua provider: bot/`[deleted]`/`[removed]`,
  bahasa Inggris, konteks klub untuk nama ambigu (aturan 17), dan kuota
  `max_texts_per_player`.
- `subreddit` tidak ada di item `comment` skema `default`; nilainya diwarisi dari
  post induk lewat `postId`, lalu dari `permalink` sebagai cadangan.
- Post hanya dipakai sebagai pembawa konteks, tidak disimpan sebagai teks:
  `unit_type` terkunci ke `comment`/`sentence` (PRD §8), sama seperti jalur OAuth.

## Kalau disetujui

1. Buka <https://www.reddit.com/prefs/apps> — form "create app" muncul lagi setelah akun di-allowlist.
2. Buat app tipe **script**, redirect `http://localhost:8080`.
3. Salin `client id` (di bawah nama app) dan `secret` ke `.env`.
4. `make scrape-verify` lalu lanjut ke pilot.

Catat tanggal persetujuan di [`decisions.md`](decisions.md) saat kredensial masuk.

## Kalau ditolak atau belum ada jawaban sampai Hari 2 pagi

Jangan menunggu. PRD §12 dan PLAN-1WEEK §1 sudah menetapkan jalannya:

> "Keputusan di Hari 1; jika gagal, YouTube + artikel jadi sumber utama dan laporan menyebutnya."

Artinya:

1. **YouTube jadi sumber teks utama** (orang C): komentar + transkrip dari channel whitelist, `playlistItems.list`, bukan `search.list`.
2. **Artikel scouting jadi sumber kedua** (orang C): `trafilatura`, whitelist domain, tanpa menembus paywall.
3. **Reddit ditulis di laporan sebagai sumber yang dicoba dan gagal diakses**, beserta tanggal permohonan dan hasilnya. Itu temuan metodologis yang sah, bukan kegagalan yang disembunyikan.
4. Kode Tahap B tetap di repo dan tetap diuji — kalau izin datang di Hari 5–6, `make scrape-pilot` bisa langsung jalan tanpa menulis ulang apa pun.

Yang **tidak boleh** dilakukan: mencari jalan pintas (scraping lewat `old.reddit.com`, RSS, atau proxy tanpa izin). Itu melanggar ToS dan aturan AGENTS.md bagian "Konvensi kerja".

## Dampak ke jadwal

| Hari | Rencana awal | Kalau akses Reddit macet |
|---|---|---|
| 1 | Verifikasi nama subreddit + pilot | Kirim tiket, catat tanggal, alihkan ke YouTube |
| 2 | Pilot 20 pemain, cek 100 teks | Pilot YouTube + artikel; relevansi diukur di sana |
| 3 | Scraping penuh | Scraping penuh YouTube |
| 4 | Cleaning + labeling | Sama, tidak berubah |

Yang bergeser hanya **sumber**, bukan urutan pipeline. Labeling 25 teks per orang
dan skema tabel tetap di Hari 4.
