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
Low: under 1,500 requests total for the whole week, spaced at least one second
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

### 3. Actor pihak ketiga di marketplace (Apify dan sejenisnya) — **melanggar ToS, tidak dipakai**

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
   penyedia jasa scraping: *Reddit, Inc. v. SerpApi LLC*, No. 25-cv-8736
   (S.D.N.Y.), dengan klaim DMCA yang sebagian besar lolos motion to dismiss
   pada 31 Juli 2026. Angka 22,3% run sukses pada actor terbesar adalah gejala
   blokir itu, bukan bug.

3. **Datanya tidak layak untuk riset.** Actor yang bertahan di "public feed"
   memberi `score`, `upvoteRatio`, `numComments` = 0 dan komentar tanpa `depth`
   maupun `parentId`. `automation-lab` menulis sendiri: *"coverage remains
   unverified"*, `sourceCommentCount` bisa `null`, dan tiap baris membawa
   `warnings` tentang field yang hilang. Untuk proyek yang metrik kelulusannya
   adalah **relevansi retrieval ≥ 85% dan jumlah teks per pemain** (PRD §11),
   data yang bolong tanpa bisa dilacak asal-usulnya adalah masalah, bukan solusi.
   Angka di laporan juga harus bisa ditelusuri ke skrip di repo (AGENTS.md) —
   dataset dari marketplace tidak bisa direproduksi oleh dosen.

**Kesimpulan:** satu-satunya jalan yang sah dan berfungsi adalah formulir Data API
di bawah. Ketiga alternatif di atas tidak dipakai, dan alasannya dicatat di sini
supaya tidak ada yang mengulanginya.

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
