# Validasi Numerik & Tolok Ukur Posisi (Tahap A/E)

Dihasilkan otomatis oleh `src/score/run_metrics.py` (ambang menit >= **900**, bootstrap **1000x**).

## Cakupan Data

- Populasi total: **340** pemain
- Market value FotMob tersedia: **340/340**
- Rating FotMob (`stats/rating.json`) tersedia: **288/340** (52 pemain tidak masuk papan peringkat leaderboard FotMob)
- Sampel teks terkunci: **70** pemain (**60/70** memiliki rating di `rating.json`)

> **Catatan bias cakupan leaderboard:** kolom *Median Rating (95% CI)* dihitung hanya dari pemain yang memiliki entri di `rating.json` (**288/340**), yang umumnya memiliki menit main lebih tinggi daripada pemain tanpa rating. Untuk posisi dengan *n* kecil (mis. GK, *n* = 20 rated), interval kepercayaan bootstrap harga dan rating melebar secara alami.

## Ringkasan per Posisi (dengan Interval Kepercayaan Bootstrap 95%)

| Posisi | Pemain | Punya Rating | Sampel (Rated) | Median Rating (95% CI) | P40 Harga EUR (95% CI) |
|---|---|---|---|---|---|
| GK | 24 | 20 | 18 (15) | 6.92 (6.82–6.96) | €16.12M (€6.65M–€19.05M) |
| DEF | 125 | 95 | 18 (11) | 6.92 (6.87–7.00) | €21.50M (€17.98M–€24.67M) |
| MID | 102 | 91 | 17 (17) | 6.95 (6.89–7.03) | €25.95M (€20.29M–€32.60M) |
| FWD | 89 | 82 | 17 (17) | 6.79 (6.67–6.87) | €25.45M (€20.65M–€29.89M) |

## Pemain Sampel Tanpa Rating di `rating.json`

Pemain di bawah ini tidak tercantum di leaderboard `leagueseasondeepstats` (`rating.json`), sehingga `rating_above_median` bernilai `<NA>` (bukan `False`). Stage E wajib memperlakukannya sebagai tidak tervalidasi rating, bukan otomatis di bawah median.

| player_id | Nama | Posisi | Klub | Menit | Harga (EUR) |
|---|---|---|---|---|---|
| `fotmob_1053838` | Morato | DEF | Nottingham Forest | 1342 | €17.83M |
| `fotmob_419664` | Tyrone Mings | DEF | Aston Villa | 1323 | €3.83M |
| `fotmob_690149` | Axel Tuanzebe | DEF | Burnley | 1202 | €3.49M |
| `fotmob_769895` | Matthijs de Ligt | DEF | Manchester United | 1170 | €49.55M |
| `fotmob_1413846` | Jorrel Hato | DEF | Chelsea | 1142 | €50.07M |
| `fotmob_1114979` | Emmanuel Agbadou | DEF | Wolverhampton Wanderers | 1101 | €21.27M |
| `fotmob_258269` | Victor Nilsson Lindelöf | DEF | Aston Villa | 944 | €5.52M |
| `fotmob_967941` | Mads Hermansen | GK | West Ham United | 1620 | €18.89M |
| `fotmob_280287` | Sam Johnstone | GK | Wolverhampton Wanderers | 1080 | €4.71M |
| `fotmob_746395` | Aaron Ramsdale | GK | Newcastle United | 1003 | €16.89M |
