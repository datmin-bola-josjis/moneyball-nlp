# Relevansi Retrieval Reddit (Tahap B)

- Teks dilabeli: **100** dari 100 ditarik (0 kosong)
- Relevan: **94**
- Relevansi: **94.0%** (target PRD §11: >= 85%)
- Status: **LULUS**

Label diusulkan oleh Codex setelah membaca setiap komentar dan disetujui oleh penanggung jawab sebelum disalin ke lembar penilaian. Hasil ini mengukur relevansi retrieval dengan label berbantuan AI.

Cara sampel diambil: `random.sample` dengan seed `text_sample.random_seed` dari `config/config.yaml` — sampel acak seragam atas semua komentar di file `texts_reddit_*.jsonl` yang dipakai. Seednya sama untuk semua anggota tim, jadi lembar yang sama bisa dibuat ulang. `LULUS` hanya diberikan bila minimal 100 teks dilabeli.

## Per subreddit

| Subreddit | Dilabeli | Relevan | Relevansi |
|---|---|---|---|
| r/NUFC | 24 | 22 | 92% |
| r/WWFC | 22 | 22 | 100% |
| r/safc | 14 | 12 | 86% |
| r/Burnley | 10 | 10 | 100% |
| r/reddevils | 9 | 9 | 100% |
| r/LiverpoolFC | 9 | 8 | 89% |
| r/chelseafc | 8 | 7 | 88% |
| r/AFCBournemouth | 3 | 3 | 100% |
| r/avfc | 1 | 1 | 100% |

## Contoh teks tidak relevan (wajib ada di laporan)

- `fotmob_1050166` r/NUFC: I completely disagree, and I am actually quite astounded with this take (I usually agree with a lot of stuff you say). You cannot group people together like that, there are plenty of different motivations for people bein
- `fotmob_940446` r/safc: How did Le Bris convince him to join us in the Championship never mind the PL is what baffles me, he is a joy to watch and one of my favourites to wear the shirt. We are blessed with stand out players this season Reofs M
- `fotmob_1050166` r/NUFC: Eddie's definitely staying but he shouldn't have stayed. Liverpool had the balls to sack a manager who won them the league and got them CL. We've kept a manager who's played awful football for 15 months, finished 12th, b
- `fotmob_1067763` r/safc: He's strong, quick, can carry the ball well and got a decent shot on him. Go watch his goal versus Coventry last season as best example of that. I was lucky enough to see it live. I'd say the biggest weaknesses are losin
- `fotmob_917802` r/chelseafc: This sub hypes any Donkey with the surname Fofana
- `fotmob_806552` r/LiverpoolFC: i could be looking too far into it but i’m seeing the player’s farewell social media posts towards Slot and doesn’t really seem like there’s too much emotion there. Curtis Jones - “Respect you as a man for what you gave
