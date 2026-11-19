# Pipeline entry points. See docs/PLAN-1WEEK.md §7 for the target layout.
#
# Target: `make pipeline` runs the whole thing, raw data to output.
# Stages are runnable individually so a failure is cheap to isolate.

# Interpreter: project venv first, then `python3`, then `python`.
# `python3` on Windows is a Microsoft Store alias that fails when run, so it is
# probed instead of assumed; `make test PYTHON=python` overrides.
VENV := .venv
PYTHON ?= $(shell \
  if [ -x "$(VENV)/bin/python" ]; then echo "$(VENV)/bin/python"; \
  elif python3 -c "print(1)" >/dev/null 2>&1; then echo python3; \
  else echo python; fi)

.DEFAULT_GOAL := help
.PHONY: help setup venv check config sample metrics fetch-players lock-sample population scrape scrape-verify scrape-pilot scrape-arctic scrape-youtube cleaning review review-score labels-status scrape-articles link dedupe nlp score viz pipeline test clean

# pytest is preferred, but the suite is plain unittest, so a machine where
# `make setup` has not run yet can still verify the code.
ifeq ($(shell $(PYTHON) -c "import pytest" >/dev/null 2>&1 && echo yes),yes)
TEST_CMD = $(PYTHON) -m pytest tests/ -q
else
TEST_CMD = $(PYTHON) -m unittest discover -s tests -t . $(if $(V),-v,)
endif

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create the project virtualenv at .venv
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip

setup: ## Install dependencies (uses .venv when present)
	$(PYTHON) -m pip install -r requirements.txt

check: config ## Validate config and run tests
	$(TEST_CMD)

config: ## Validate config/config.yaml parses and keeps its invariants
	$(PYTHON) -m src.validate_config

# ---------------------------------------------------------------- Stages
# Each stage reads from data/ and writes to data/, never overwriting raw input.

fetch-players: ## Stage A - fetch one FotMob payload per player (cached, resumable)
	$(PYTHON) -m src.population.fetch_players

population: ## Stage A - build players.parquet and the text sample (dry run)
	$(PYTHON) -m src.population.run_population

lock-sample: ## Stage A - same as population, then lock the sample file
	$(PYTHON) -m src.population.run_population --lock

scrape: ## Stage B - retrieve texts per player (reddit, youtube, article)
	$(PYTHON) -m src.scrape.run

scrape-verify: ## Stage B Day 1 - verify configured subreddit names against Reddit
	$(PYTHON) -m src.scrape.run --verify

scrape-pilot: ## Stage B Day 2 - pilot scraping, PILOT=20 players by default
	$(PYTHON) -m src.scrape.run --pilot $(or $(PILOT),20)

scrape-arctic: ## Stage B - Reddit via Arctic Shift (no credentials needed)
	$(PYTHON) -m src.scrape.run --provider arctic $(if $(PILOT),--pilot $(PILOT),)

scrape-youtube: ## Stage B - YouTube comments from the whitelist channels
	$(PYTHON) -m src.scrape.youtube $(if $(PILOT),--pilot $(PILOT),)

cleaning: ## Stage B - render the YouTube cleaning table from a run summary
	$(PYTHON) -m src.scrape.cleaning $(if $(RUN),--run $(RUN),)

review: ## Stage B Day 2 - draw 100 scraped texts for manual relevance labels
	$(PYTHON) -m src.scrape.run --sample $(if $(N),--n-sample $(N),) $(if $(SOURCE),--source $(SOURCE),) $(if $(TAG),--tag $(TAG),)

review-score: ## Stage B - score the filled review sheet into reports/retrieval_relevance.md
	$(PYTHON) -m src.scrape.run --score $(if $(SOURCE),--source $(SOURCE),)

labels-status: ## Stage B - progress and format check for the three manual labelling sheets
	$(PYTHON) -m src.scrape.labels

scrape-articles: ## Stage B (bonus) - article paragraphs from whitelisted domains; disabled in config by default
	$(PYTHON) -m src.scrape.article $(if $(PILOT),--pilot $(PILOT),) $(if $(URLS),--urls $(URLS),)

link: ## Stage C - entity linking and text filtering
	$(PYTHON) -m src.link.resolve

dedupe: ## Stage C - drop texts that appear in both Reddit and YouTube
	$(PYTHON) -m src.link.dedupe $(if $(REDDIT_TAG),--reddit-tag $(REDDIT_TAG),) $(if $(YOUTUBE_TAG),--youtube-tag $(YOUTUBE_TAG),)

nlp: ## Stage D - sentiment and aspect extraction
	$(PYTHON) -m src.nlp.analyze

metrics: ## Stage A/E - numeric metrics, ratings and positional z-scores
	$(PYTHON) -m src.score.run_metrics

score: ## Stage E - text quality score, validation, candidate flagging
	$(PYTHON) -m src.score.rank

viz: ## Stage F - figures and candidate table
	$(PYTHON) -m src.viz.report

# `pipeline` runs the retrieval path the team actually uses. `scrape` (the OAuth
# path) is deliberately not a prerequisite: Reddit closed self-service app
# creation in Nov 2025 and there are no credentials, so chaining it killed the run
# at Stage B before any later stage could be reached. `scrape-arctic` is the route
# decided in docs/decisions.md (2026-11-12) and needs no credentials.
# `scrape-articles` is excluded because that source is disabled in config and its
# entry point exits non-zero on purpose.
#
# This is not a clean-clone guarantee. Two prerequisites still need external
# state: `scrape-youtube` requires YOUTUBE_API_KEY in `.env`
# (`src/scrape/youtube_client.api_key` raises SystemExit without it), and
# `population` requires cached FotMob payloads from `make fetch-players`. YouTube
# is a primary text source (AGENTS.md), so leaving it out would make the pipeline
# fail to reproduce the corpus rather than make it self-contained.
#
# `dedupe` and `metrics` are prerequisites because later stages read what they
# write: `link` reads `texts_deduped.parquet`, which only `dedupe` produces, and
# `score` reads `metrics_numeric.parquet`, which only `metrics` produces. Without
# them the pipeline silently consumed whatever stale copy was left on disk.
PIPELINE_STAGES := population metrics scrape-arctic scrape-youtube dedupe link nlp score viz

# The order above is a real dependency, not a preference, but `pipeline: $(...)
# only expresses it to serial make: as plain prerequisites these nine targets are
# siblings, and `make -j` would happily start `link` before `dedupe` finishes -
# which is precisely the stale-parquet bug this ordering was meant to remove.
# `.NOTPARALLEL` on this one target keeps the recipe serial under -j while the
# other targets stay parallel. Verified: `make -j4 -n pipeline` lists the stages
# in order only because of this line.
.NOTPARALLEL: pipeline

pipeline: $(PIPELINE_STAGES) ## Run the full pipeline end to end
	@echo "pipeline complete"

test: ## Run test suite
	$(TEST_CMD)

clean: ## Remove caches and build artifacts (never touches data/raw)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	@echo "cleaned (data/raw preserved)"
