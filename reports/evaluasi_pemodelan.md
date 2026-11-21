# Evaluasi Pemodelan (Tahap D)

- Status data: **LENGKAP** — 136 dari 136 label terisi, 0 kalimat tanpa keputusan mayoritas
- Masalah baca: {'aspek tidak dikenali': 0}

## Entity linking (presisi; recall tidak terukur karena kalimat yang dibuang B tidak ikut sampel)

- Presisi: **98.0%** (98/100), 95% CI 93.0%–99.4%; target PRD §11 ≥ 85%: **tercapai**

| Kelompok | Benar | Total | Presisi |
|---|---|---|---|
| link_confidence <0.4 | 38 | 38 | 100.0% |
| link_confidence 0.4-0.7 | 27 | 28 | 96.4% |
| link_confidence >=0.7 | 33 | 34 | 97.1% |
| flag crowded | 33 | 33 | 100.0% |
| flag lowercase_only | 6 | 6 | 100.0% |
| flag lowercase_only,crowded | 3 | 3 | 100.0% |
| flag none | 56 | 58 | 96.6% |

Simulasi pemotongan (informasi saja; ambang dipilih tim, lalu dicatat di decisions.md):

| min_confidence | Kalimat tersisa | Presisi |
|---|---|---|
| 0.2 | 90/100 | 97.8% |
| 0.4 | 74/100 | 97.3% |
| 0.6 | 38/100 | 97.4% |

## Sentimen (VADER + lexicon bola), hanya kalimat yang benar membahas pemain

- Akurasi: **52.0%** (51/98), 95% CI 42.3%–61.7%; target ≥ 75%: **belum tercapai**
- Pembanding: selalu menebak 'positive' akan benar 44.9%
- Macro-F1: 0.497

| Kelas | Presisi | Recall | F1 | Jumlah gold |
|---|---|---|---|---|
| positive | 0.59 | 0.61 | 0.60 | 44 |
| neutral | 0.50 | 0.48 | 0.49 | 31 |
| negative | 0.41 | 0.39 | 0.40 | 23 |

Matriks kebingungan (baris = label manual, kolom = mesin):

| gold \ mesin | positive | neutral | negative |
|---|---|---|---|
| positive | 27 | 10 | 7 |
| neutral | 10 | 15 | 6 |
| negative | 9 | 5 | 9 |

## Aspek (kamus kata kunci, kata utuh)

- Presisi 52.4%, recall 28.2% (TP 11, FP 10, FN 28) pada 98 kalimat
- Jumlah aspek per label manual: {'defending': 3, 'positioning': 10, 'finishing': 7, 'mentality': 7, 'passing': 4, 'stamina': 3, 'pace': 2, 'dribbling': 3}

## Kesepakatan antar-anotator (kalimat overlap)

- Cohen's κ membahas pemain: rata-rata 0.00 dari 3 pasangan (min 0.00, maks 0.00)
- Cohen's κ sentimen: rata-rata 0.61 dari 6 pasangan (min 0.45, maks 0.86)

## Contoh salah sentimen (wajib ada di laporan)

- manual **neutral**, mesin **positive**: Win win scenario for semenyo in the title race
- manual **negative**, mesin **neutral**: Tchatchoua just tackled Mane.
- manual **neutral**, mesin **positive**: I think Cuenca has been outstanding since Bassey left for AFCON and I wouldn’t drop him.
- manual **positive**, mesin **neutral**: Jensen is a bees legend.
- manual **neutral**, mesin **positive**: RJ - Colwill - Fofana - Cucurella our defense has literally nothing to do with the chuckle brothers.
- manual **positive**, mesin **neutral**: I'm not saying he needs to bulk up to Brobbey level.
- manual **negative**, mesin **positive**: Ramsdale C: He ultimately wasn’t as trustworthy long term as an aging and underperforming Nick Pope.
- manual **negative**, mesin **neutral**: I would have said Bassey but Robinson has been iffy lately...
- manual **neutral**, mesin **negative**: Most likely the referee saw the challenge by Pope and gave the penalty yet was taken on a detour by VAR on Pope's contact with the ball which was a complete red herring.
- manual **negative**, mesin **positive**: I'm all for selling Ramsdale, hopefully Southampton won't notice.

## Contoh tautan salah (kalimat bukan tentang pemain)

- confidence 0.80, flag `-`: Ramsdale basically lost because of his poor maths 😭 100/114 points has to mean 14 dropped, 4 draws for 8, 2 losses for 6.
- confidence 0.53, flag `-`: Was skeptical of his attacking contributions/end product and his chemistry with Trossard and Martinelli.

Catatan: interval 95% pada sampel sekitar 100 kalimat lebar (±8–10 poin); laporkan angka beserta intervalnya, bukan angka tunggal.
