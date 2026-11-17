# Tabel Cleaning YouTube (Tahap B)

Run: `full-20261113-025149`. Angka diambil dari `summary.json` run itu, dihitung oleh
`src/scrape/cleaning.py` dari penghitung yang ada di
`src/scrape/youtube.py::records_from_comment` — bukan ditulis manual.

## Komentar

| Filter | Dibuang | Porsi dari diperiksa | Alasan |
|---|---|---|---|
| Terlalu pendek | 13170 | 37,9% | kurang dari `min_words` kata (config) |
| Bukan bahasa Inggris | 227 | 0,7% | deteksi bahasa |
| Bot / spam | 0 | 0,0% | penanda bot |
| Tanpa tanggal | 0 | 0,0% | `publishedAt` kosong atau tidak valid |
| Di luar musim | 288 | 0,8% | di luar `league.season_start`..`season_end` |
| Duplikat dalam satu pemain | 25 | 0,1% | `text_clean_hash` sudah dipakai |
| Nama tidak teratasi | 19986 | 57,5% | aturan 17 / `AliasIndex` |
| **Diperiksa** | **34750** | 100% | pasangan (pemain, komentar) |
| **Lolos menjadi komentar** | **1054** | 3,0% | |

Kalimat yang lolos: **1105**.

## Kalimat

Kalimat disaring terpisah, setelah komentarnya lolos. Kalimat yang gugur
tidak membatalkan komentarnya.

| Filter | Dibuang | Alasan |
|---|---|---|
| Nama tidak teratasi | 939 | aturan 17 / `AliasIndex` |

## Sebaran kanal

Komentar yang lolos per kanal, di samping jumlah unggahan dalam musim
dari kanal itu. Unggahan bukan satu-satunya penentu: kanal dengan
banyak video bisa menyumbang sedikit komentar bila videonya jarang
menyebut pemain sampel. Bandingkan kedua kolom sebelum menyimpulkan
bias sumber.

| Kanal | Video dalam musim | Komentar | Porsi komentar |
|---|---|---|---|
| Sky Sports Premier League | 2075 | 747 | 70,9% |
| The Athletic FC | 317 | 144 | 13,7% |
| Premier League | 1329 | 104 | 9,9% |
| Tifo Football | 287 | 31 | 2,9% |
| The Overlap | 973 | 28 | 2,7% |
| **Total** | **4981** | **1054** | 100% |

## Catatan cara membaca

- Satuannya **pasangan (pemain, komentar)**, bukan komentar unik. Komentar
  yang sama diperiksa sekali untuk setiap pemain yang namanya mungkin
  disebut. Jadi angka "diperiksa" lebih besar dari jumlah komentar di
  korpus, dan itu memang yang ingin dijelaskan: kenapa teks ini tidak
  menjadi bukti untuk pemain ini.
- Baris diperiksa = lolos + semua filter. Selisih yang tidak terhitung: **0** (komentar yang bikin `kept_comments` mencapai kuota di tengah halaman, jadi tidak sempat diperiksa).
- Angka ini **tidak berubah** setelah teks Reddit dari B masuk: tabel ini
  hanya menjelaskan jalur YouTube.

## Perintah

```bash
make cleaning                       # dari run terbaru
make cleaning RUN=<nama-folder-run>  # dari run tertentu
```
