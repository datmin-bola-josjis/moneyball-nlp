<div align="center">

# moneyball-nlp

### Finding undervalued Premier League players from public discussion, then checking that reading against performance data

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![pandas](https://img.shields.io/badge/pandas-2.2%2B-150458?logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![Status](https://img.shields.io/badge/status-course%20prototype-orange)]()
[![Season](https://img.shields.io/badge/season-2025%2F26-38003c?logo=premierleague&logoColor=white)]()

</div>

> A note on scope before you read further: this is a one-week Data Mining course prototype (Semester 5, four people), not a production system. Stage A runs end to end and Stage B (Reddit retrieval) is written; the NLP, scoring and output stages are not. Every section below separates what runs today from what is planned. See [Development Status](#development-status) for the breakdown, with the exact command behind each claim.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Pipeline Stages](#pipeline-stages)
3. [Quick Start](#quick-start)
4. [Stage A in Practice](#stage-a-in-practice)
5. [Stage B in Practice](#stage-b-in-practice)
6. [Repository Navigation](#repository-navigation)
7. [Tech Stack](#tech-stack)
8. [Evaluation Targets](#evaluation-targets)
9. [Data Handling](#data-handling)
10. [Known Limitations](#known-limitations)
11. [Development Status](#development-status)
12. [Open Decisions](#open-decisions)
13. [Contributing](#contributing)

---

## What It Does

**Research question:** can quality signals taken from text, as aspect-level sentiment, identify low-cost players whose performance holds up in the numbers?

Text drives the analysis. Market value supplies the price, and performance data supplies the check. The player population comes from structured roster data rather than from text, so that players nobody discusses are not silently excluded.

A player is flagged undervalued when the text quality score is at or above the 75th percentile for their position, market value at or below the 40th percentile, and their rating above the positional median. Those thresholds, the season, the source whitelist and the per-source quotas all live in [`config/config.yaml`](config/config.yaml). Nothing league-specific is hardcoded in the scrapers.

---

## Pipeline Stages

| Stage | What it does | Module | Code today |
|---|---|---|---|
| **A.** Population | Roster for all 20 clubs, minutes played, internal `player_id`, transliterated name aliases. Locks the text sample of 70 players. | `src/population/` | Runs end to end |
| **A/E.** Numeric metrics | Per-90 stats, average rating, positional rating z-score. | `src/score/metrics.py`, `run_metrics.py` | Runs end to end |
| **B.** Retrieval | Player-centric Reddit and YouTube comment search, bounded by the season window and source whitelists. | `src/scrape/` | Reddit works through three providers; YouTube comments implemented (`make scrape-youtube`), transcripts & articles pending |
| **C.** Linking | Sentence-level entity linking with club context, plus date, language and cross-source dedupe. | `src/link/` | `dedupe.py` implemented; `resolve.py` not started |
| **D.** NLP | VADER sentiment per sentence, aspect assignment by keyword dictionary, buzz volume per player. | `src/nlp/` | Empty package |
| **E.** Scoring | Text Quality Score, evidence labels, candidate and overhyped flags. | `src/score/` | Only the numeric half exists |
| **F.** Output | Candidate table, scatter plot, aspect heatmap by position. | `src/viz/` | Empty package |

`make pipeline` chains all six and does not finish yet: it stops at the first empty stage. Per-stage targets exist so a failure is cheap to isolate.

---

## Quick Start

### Prerequisites

| Tool | Version | Required for |
|---|---|---|
| Python | 3.10 or newer (verified on 3.14.8) | Everything |
| `make` | any | Pipeline targets |
| Reddit Data API credentials | — | Only the `oauth` provider. Arctic Shift needs none |
| YouTube Data API key | — | Only Stage B YouTube (`make scrape-youtube`) |

### Setup

```bash
git clone https://github.com/datmin-bola-josjis/moneyball-nlp.git
cd moneyball-nlp

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # only needed for the OAuth and Apify paths
make config             # validates config/config.yaml
make check              # config validation plus the test suite
```

On a machine where the root filesystem is read-only, `pip install` into the user site-packages fails. Keep the virtualenv inside the repository, as above; the `Makefile` picks up `.venv/bin/python` automatically.

At the time of writing this README, `make check` reports **306 passed** and `make config` reports `config ok: 12 sections, 20 clubs, source=fotmob`.

---

## Stage A in Practice

Stage A is finished and its output is committed. Run it in this order:

```bash
make fetch-players   # 340 FotMob payloads, cached per player, resumable
make population      # rebuilds players.parquet, prints the sample census (dry run)
make lock-sample     # writes text_sample.parquet and sets text_sample.locked: true
make metrics         # metrics_numeric.parquet with per-position rating z-scores
```

Already on disk and verified:

| Artefact | Content | In git |
|---|---|---|
| `data/processed/text_sample.parquet` | 70 players, 17 columns, the locked sample | Yes |
| `data/processed/players.parquet` | 340 players, 20 clubs | No |
| `data/processed/metrics_numeric.parquet` | 340 rows, 28 columns, 288 with a rating z-score | No |
| `data/raw/fotmob/players/` | 340 per-player payloads | No |

The sample is stratified by position group crossed with market-value quartile, with the seed from config. Its shape: GK 18, DEF 18, MID 17, FWD 17, and every one of the 16 cells holds 4 or 5 players.

Market value and rating both come from FotMob. Transfermarkt returns HTTP 405 on every path, including the homepage, and `soccerdata` has no Transfermarkt module, so that route was abandoned; the reasoning is recorded in [`docs/decisions.md`](docs/decisions.md).

> **Note on `make population`.** Dry-run `make population` validates the sample and preserves `price_quartile`, `stratum`, and `in_text_sample` from any existing locked sample file without touching `data/processed/text_sample.parquet`.

---

## Stage B in Practice

Reddit can be reached three ways. Arctic Shift is the one that runs today, because it needs no credentials:

```bash
make scrape-arctic PILOT=20   # 20 players spread across the market-value range
make review                   # draws 100 texts into data/interim/review_relevance.csv
# label each row y/n by hand, then:
make review-score             # writes reports/retrieval_relevance.md, must clear 85%
make scrape-arctic            # full run over the locked sample
```

The other two providers:

```bash
python -m src.scrape.run --provider oauth                    # default, needs REDDIT_CLIENT_ID/SECRET
python -m src.scrape.run --provider apify --estimate-cost    # cost estimate only, no request sent
```

Apify is **disabled** on purpose: the marketplace actor breaches Reddit's User Agreement §7 and PRD §13. The code is kept as a measured record of that path, not as something to run.

Why Arctic Shift: since November 2025 Reddit no longer self-serves app registration, `prefs/apps` redirects to the Responsible Builder Policy, and the Data API client ID only arrives after a manual request is approved. Unauthenticated `.json` calls return 403, `old.reddit.com` serves a placeholder page, and RSS carries posts but no comments. Arctic Shift serves archived comments without authentication. This is a deliberate, recorded deviation from the "no detours" working rule; see [`docs/tahap-b-reddit.md`](docs/tahap-b-reddit.md) and the decision log for what was tried and rejected.

Output per run:

```text
data/raw/reddit/<tag>-<timestamp>/texts.jsonl      raw records, never overwritten
data/raw/reddit/<tag>-<timestamp>/summary.json     counts per player, requests made
data/raw/reddit/<tag>-<timestamp>/<player_id>.comments.json   Arctic Shift raw page cache
data/interim/texts_reddit_<tag>.jsonl              handoff copy for the next stage
```

Every record carries `player_id`, `source`, `unit_type` (`comment` or `sentence`), `text_clean_hash` for cross-source dedupe, `created_at`, `url`, `subreddit` and the `matched_alias` that triggered the hit. Comment authors are checked for bot markers and then discarded; the persisted payloads keep a fixed whitelist of fields so author identity cannot leak back in.

A run logs the number of texts kept per player and lists players with none, so a silent empty scrape cannot pass as success. A full run refuses to start until `data/processed/text_sample.parquet` exists and `text_sample.locked` is true. A `--pilot` run reads the sample but skips that lock check.

YouTube comment retrieval is implemented by person C (`make scrape-youtube`, `make cleaning`, and cross-source dedupe via `make dedupe`); see [`docs/tahap-b-youtube.md`](docs/tahap-b-youtube.md). Video transcripts (`include_transcript`) and article retrieval are not implemented yet. `src/scrape/` is shared, so the text helpers, alias index, and population reader are reused across both sources.

---

## Repository Navigation

```text
config/config.yaml   league, season, whitelist, thresholds, quotas, sampling seed
docs/                PRD, weekly plan, overview, decision log, Reddit access notes
src/population/      stage A, population build, sampling, alias handling
src/scrape/          stage B, Reddit retrieval, alias index, relevance review
src/link/            stage C, entity linking and text filtering
src/nlp/             stage D, sentiment and aspect extraction
src/score/           stage A/E numeric metrics; stage E text scoring to come
src/viz/             stage F, figures and candidate table
data/raw/            never overwritten, never committed
data/processed/      cleaned data; text_sample.parquet holds the locked sample
data/interim/        stage handoffs and the relevance review sheet
reports/figures/     figures produced by the pipeline
tests/               alias matching, date filters, schema and scraping behaviour
```

### Documents

| File | Contents |
|---|---|
| [`docs/GAMBARAN-BESAR.md`](docs/GAMBARAN-BESAR.md) | Short overview of the project and each person's role. Start here. |
| [`docs/PRD.md`](docs/PRD.md) | Scope, data sources, stages A to F, dataset schema, definitions, metrics, risks, ethics |
| [`docs/PLAN-1WEEK.md`](docs/PLAN-1WEEK.md) | Role split, seven-day schedule, report structure |
| [`docs/decisions.md`](docs/decisions.md) | Every threshold change and technical decision, with the reasoning |
| [`docs/tahap-b-reddit.md`](docs/tahap-b-reddit.md) | Reddit access record: what was tried, what was rejected, and why |
| [`docs/tahap-b-youtube.md`](docs/tahap-b-youtube.md) | YouTube retrieval: channels, pipeline, measured numbers, limitations |
| [`AGENTS.md`](AGENTS.md) | Rules for AI agents and contributors |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup, branch naming, commit format |

---

## Tech Stack

| Layer | Choice | State |
|---|---|---|
| Data frames | `pandas`, `pyarrow` | Installed and used |
| HTTP | `requests` | Installed and used |
| Config | `PyYAML`, `python-dotenv` | Installed and used |
| Testing | `pytest` (the suite is plain `unittest` and also runs without it) | Installed and used |
| Sentiment | `vaderSentiment` | Declared, not yet imported |
| Aspect / linking | `rapidfuzz`, `spacy` | Declared, not yet imported |
| Visuals | `matplotlib`, `plotly` | Declared, not yet imported |
| Scraping extras | `praw`, `soccerdata`, `trafilatura`, `google-api-python-client`, `youtube-transcript-api` | Declared, not imported |

Only the first four groups are installed in the verified environment, which is enough for the whole of Stage A and the Reddit paths. Note that `requirements.txt` pins `pandas>=2.2,<3.0` while the verified environment runs pandas 3.1.1; a fresh `pip install -r requirements.txt` will resolve to 2.3.x. The suite has not been re-run against 2.x.

`praw`, `soccerdata` and `trafilatura` are declared but never imported: the Reddit client is hand-written on `requests`, and the population build reads FotMob JSON directly.

---

## Evaluation Targets

Every claim is meant to have a number behind it, and every number should trace back to a script here.

| Metric | Target | How it is measured |
|---|---|---|
| Entity linking accuracy | 85% or higher | 100 texts labelled by four people |
| Retrieval relevance | 85% or higher | 100 randomly sampled texts, checked by hand |
| Sentiment accuracy | 75% or higher | Model labels against 100 manual labels |
| Inter-annotator agreement | Cohen's kappa, reported as measured | 12 overlapping texts labelled by all four |
| Evidence sufficiency | 30 or more texts scored fully, 10 to 29 marked limited, under 10 not scored | `n_texts` per player |
| Main evidence metric | Share of text-based candidates that also sit above their positional rating median, reported; 60% or higher reads as a useful text signal | `player_summary` join |

Players with fewer than 10 texts are labelled insufficient evidence and left out of the candidate table rather than scored on thin data. No metric in this table has been produced yet: the relevance review sheet has never been filled, so retrieval relevance is unmeasured.

---

## Data Handling

Only public data is collected. The project does not bypass paywalls or other access controls and follows `robots.txt` and site terms. Comment authors are never stored; a whitelist of persisted fields enforces this, and an audit found no usernames remaining after the fix. Raw data is not redistributed, and neither is any raw Reddit payload: it stays out of git and out of the shared repository.

---

## Known Limitations

The text sample covers 70 players rather than the whole league, so findings drawn from text apply to that sample. Coverage is one league and one season. Sentiment uses VADER with a keyword dictionary for aspects, which handles sarcasm and football slang poorly; those failures belong in the report rather than being filtered out. Percentiles computed within a position are unstable at the tails because each positional group is small, so ranks and bootstrap intervals should accompany any percentile. "Hidden gem" in the Premier League reads closer to *underrated* than to unknown. Compound surnames are a known recall hole: aliases are built from the last token, so `Bruun Larsen` never matches, and a measured pilot showed three such comments dropped for one player.

---

## Development Status

| Area | State | Evidence |
|---|---|---|
| Population and locking (Stage A) | **Implemented** | `make population`, `make lock-sample`; 340 players, 20 clubs, 70-player locked sample |
| Numeric metrics and rating z-scores | **Implemented** | `make metrics`; 340 rows, 288 ratings z-scored |
| Config validation | **Implemented** | `make config`; 12 sections, 20 clubs, source=fotmob |
| Test suite | **Implemented** | `make test`; 306 passed |
| Reddit retrieval (three providers) | **Implemented**, no full run yet | Code, tests and a 20-player pilot are written; the relevance gate has not been passed |
| Subreddit name verification | **Partial** | `make scrape-verify` needs OAuth credentials that do not exist yet |
| Relevance review tooling | **Partial** | `make review` and `make review-score` exist; no labels have been collected |
| Arctic Shift volume measurement | **Partial** | `measure_volume.py` plus 11 tests; a probe, not wired into any `make` target |
| YouTube retrieval | **Partial** | `make scrape-youtube` and `make cleaning` implemented; transcripts and human relevance gate pending |
| Article retrieval | **Not started** | Config only, disabled |
| Entity linking (Stage C) | **Partial** | `make dedupe` (`src/link/dedupe.py`) implemented; `src/link/resolve.py` not started |
| Sentiment and aspects (Stage D) | **Not started** | `src/nlp/` is an empty package |
| Text quality score and flags (Stage E) | **Not started** | Only the numeric half of `src/score/` exists |
| Figures and candidate table (Stage F) | **Not started** | `src/viz/` is an empty package; `reports/figures/` is empty |
| End-to-end pipeline | **Planned** | `make pipeline` stops at the first empty stage |

---

## Open Decisions

Three items need a human decision, none of them settled:

1. The output format the course requires: written report, presentation, or working dashboard.
2. How many numeric columns are allowed while the dataset stays predominantly string-based.
3. Whether X/Twitter is attempted. The current default is to skip it.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Work on a branch, open a pull request, and do not force push to `main`. Threshold changes go into [`docs/decisions.md`](docs/decisions.md) with the reasoning attached.

The documents under `docs/` are in Indonesian, which is the working language of the team and of the course report. Code, identifiers, comments and commit messages are in English. This README is in English because it is the outward-facing file.
