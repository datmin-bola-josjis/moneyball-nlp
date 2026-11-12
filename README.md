# moneyball-nlp

Identifying undervalued Premier League players from public discussion, then checking that reading against performance data.

Data Mining course project, Semester 5. Four people, one week. The prototype covers the Premier League 2025/26 season.

**Status:** documentation and repository scaffold are in place. Stage B (Reddit retrieval) is written; stages A and C to F are not. Nothing has been scraped yet — stage B needs the Reddit credentials in `.env` and the locked sample list from stage A.

## Research question

Can quality signals taken from text, as aspect-level sentiment, identify low-cost players whose performance holds up in the numbers?

Text drives the analysis. Market value supplies the price, and performance data supplies the check. The player population comes from structured roster data, because a pool built out of text would leave out the players nobody discusses.

## Stages

| Stage | What it does | Module |
|---|---|---|
| A. Population | Roster for all 20 clubs, minutes played, internal `player_id`, name aliases. Locks the text sample of roughly 70 players. | `src/population/` |
| B. Retrieval | Player-centric search on Reddit and YouTube, bounded by season dates and the whitelist in config. Reddit is written; YouTube is pending. | `src/scrape/` |
| C. Linking | Sentence-level entity linking with club context, plus date, language and deduplication filters. | `src/link/` |
| D. NLP | VADER sentiment per sentence, aspect assignment by keyword dictionary, buzz volume per player. | `src/nlp/` |
| E. Scoring | Text Quality Score, evidence labels, numeric validation, candidate and overhyped flags. | `src/score/` |
| F. Output | Candidate table, scatter plot, aspect heatmap by position. | `src/viz/` |

A player is flagged undervalued when the text quality score is at or above the 75th percentile for their position, market value at or below the 40th percentile, and their rating above the positional median. Those numbers live in [`config/config.yaml`](config/config.yaml) along with the season, the source whitelist and the quotas. Nothing league-specific is hardcoded in the scrapers.

## Setup

```bash
git clone https://github.com/datmin-bola-josjis/moneyball-nlp.git
cd moneyball-nlp

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # Reddit and YouTube credentials
make config             # validates config/config.yaml
```

Stage B needs credentials that are not in the repository.

- **Reddit:** access is requested, not self-served. Since November 2025 `prefs/apps` only redirects to the Responsible Builder Policy, so the client ID and secret arrive only after the manual request at <https://support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=14868593862164> is approved. [`docs/tahap-b-reddit.md`](docs/tahap-b-reddit.md) has the answers to paste and the fallback plan. Unauthenticated requests are rejected, so both values are required to verify subreddit names and to scrape.
- **YouTube:** enable YouTube Data API v3 in Google Cloud Console, then create an API key.

`.env` is in `.gitignore` and never committed. Without these credentials stage B cannot run, and stages C to F have no input.

## Stage B in practice

```bash
make scrape-verify     # Day 1 gate: every configured subreddit name really exists
make scrape-pilot      # 20 players spread across the market-value range
make review            # draw 100 scraped comments into data/interim/review_relevance.csv
# label y/n by hand, then:
make review-score      # writes reports/retrieval_relevance.md, must clear 85%
make scrape            # full run over the locked sample
```

Reddit can be reached two ways. OAuth is the default and the only sanctioned one:

```bash
python -m src.scrape.run --provider oauth        # default, needs REDDIT_CLIENT_ID/SECRET
python -m src.scrape.run --provider apify --estimate-cost   # cost only, no request sent
python -m src.scrape.run --provider apify --pilot 3         # marketplace actor, needs APIFY_TOKEN
```

The Apify provider is **disabled**: it breaches Reddit's User Agreement §7 and PRD §13.
The code is kept as a measured record of that path, not as something to run. Text comes
from OAuth if the Data API request is approved, otherwise YouTube and articles
(PRD §12). See [`docs/tahap-b-reddit.md`](docs/tahap-b-reddit.md) §3.

Output per run:

```text
data/raw/reddit/<tag>-<timestamp>/texts.jsonl    raw records, one JSON per text; never overwritten
data/raw/reddit/<tag>-<timestamp>/summary.json    counts per player, requests made
data/interim/texts_reddit_<tag>.jsonl             handoff copy, replaced by the next run of the same tag
```

Every record carries `player_id`, `source`, `unit_type` (`comment` or `sentence`), `text_clean_hash` for cross-source dedupe, `created_at`, `url`, `subreddit` and the `matched_alias` that triggered the hit. Comment authors are checked for bot markers and then discarded, never stored.

A run logs the number of texts kept per player and lists players with none, so a silent empty scrape cannot pass as success. `make scrape` refuses to start until `data/processed/text_sample.parquet` exists and `text_sample.locked` is true.

Reddit retrieval is the part written so far. YouTube and article retrieval are person C's stage and are not implemented; `src/scrape/` is shared, so the text helpers and the population reader are meant to be reused there rather than duplicated.

## Layout

```text
config/config.yaml   league, season, source whitelist, thresholds, quotas
docs/                PRD, weekly plan, overview, decision log
src/population/      stage A, population and the locked text sample
src/scrape/          stage B, Reddit, YouTube, article retrieval
src/link/            stage C, entity linking and text filtering
src/nlp/             stage D, sentiment and aspect extraction
src/score/           stage E, quality score and numeric validation
src/viz/             stage F, figures and candidate table
data/raw/            never overwritten, never committed
data/processed/      cleaned data; text_sample.parquet holds the locked sample
reports/figures/     figures produced by the pipeline
tests/               alias matching, date filters, schema checks
```

`make pipeline` is meant to run the whole thing from raw input to output. Per-stage targets exist so a failure is cheap to isolate. Only stage B (Reddit) has code behind it; the other targets still point at modules that do not exist.

## Documents

| File | Contents |
|---|---|
| [`docs/GAMBARAN-BESAR.md`](docs/GAMBARAN-BESAR.md) | Short overview of the project and each person's role. Start here. |
| [`docs/PRD.md`](docs/PRD.md) | Scope, data sources, stages A to F, dataset schema, definitions, metrics, risks, ethics |
| [`docs/PLAN-1WEEK.md`](docs/PLAN-1WEEK.md) | Role split, seven-day schedule, report structure |
| [`docs/decisions.md`](docs/decisions.md) | Every threshold change and technical decision, with the reasoning |
| [`docs/tahap-b-youtube.md`](docs/tahap-b-youtube.md) | YouTube retrieval: channels, pipeline, measured numbers, limitations |
| [`AGENTS.md`](AGENTS.md) | Rules for AI agents and contributors |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup, branch naming, commit format |

The documents are in Indonesian, which is the working language of the team and of the course report. Code, identifiers, comments and commit messages are in English.

## Data sources

| Source | Role |
|---|---|
| Transfermarkt, FBref/FotMob via `soccerdata` | Roster, position, age, club, minutes played, market value |
| r/soccer, r/PremierLeague, 20 club subreddits | Primary text source |
| YouTube channels on the whitelist | Primary text source, comments and transcripts |
| Scouting articles on the whitelist | Supplementary text |
| X/Twitter | Out of scope for this phase |

One rating source is used across the whole project. Mixing FotMob and FBref makes the positional z-scores incomparable, so the choice is made once and recorded rather than merged.

## Evaluation

Every claim is meant to have a number behind it, and every number should trace back to a script here.

| Metric | Target |
|---|---|
| Entity linking accuracy | 85 percent or higher on a manually labelled sample |
| Retrieval relevance | 85 percent or higher on 100 randomly sampled texts |
| Sentiment accuracy | 75 percent or higher on 100 manually labelled texts |
| Inter-annotator agreement | Cohen's kappa, reported as measured |
| Evidence sufficiency | 30 or more texts scored fully, 10 to 29 marked limited, under 10 not scored |

Players with fewer than 10 texts are labelled insufficient evidence and left out of the candidate table instead of being scored on thin data.

## Data handling

Only public data is collected. The project does not bypass paywalls or other access controls, and it follows `robots.txt` and site terms. Comment authors are not stored. Raw data is not redistributed; only aggregates and code are shared.

## Known limitations

The text sample covers roughly 70 players rather than the whole league, so findings drawn from text apply to that sample. Coverage is one league and one season. Sentiment uses VADER with a keyword dictionary for aspects, which handles sarcasm and football slang poorly; those failures are documented in the report rather than filtered out. Percentiles computed within a position can be unstable at the tails because each positional group is small. "Hidden gem" in the Premier League reads closer to underrated than to unknown.

## Open decisions

Three items need a human decision:

1. The output format the course requires: written report, presentation, or working dashboard.
2. How many numeric columns are allowed while the dataset stays predominantly string-based.
3. Whether X/Twitter is attempted. The current default is to skip it.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Work on a branch, open a pull request, and do not force push to `main`. Threshold changes go into [`docs/decisions.md`](docs/decisions.md) with the reasoning attached.
