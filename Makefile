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
.PHONY: help setup venv check config sample metrics fetch-players lock-sample population scrape scrape-verify scrape-pilot scrape-arctic scrape-youtube review review-score link nlp score viz pipeline test clean

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

review: ## Stage B Day 2 - draw 100 scraped texts for manual relevance labels
	$(PYTHON) -m src.scrape.run --sample $(if $(N),--n-sample $(N),) $(if $(SOURCE),--source $(SOURCE),)

review-score: ## Stage B - score the filled review sheet into reports/retrieval_relevance.md
	$(PYTHON) -m src.scrape.run --score $(if $(SOURCE),--source $(SOURCE),)

link: ## Stage C - entity linking and text filtering
	$(PYTHON) -m src.link.resolve

nlp: ## Stage D - sentiment and aspect extraction
	$(PYTHON) -m src.nlp.analyze

metrics: ## Stage A/E - numeric metrics, ratings and positional z-scores
	$(PYTHON) -m src.score.run_metrics

score: ## Stage E - text quality score, validation, candidate flagging
	$(PYTHON) -m src.score.rank

viz: ## Stage F - figures and candidate table
	$(PYTHON) -m src.viz.report

pipeline: population scrape link nlp score viz ## Run the full pipeline end to end
	@echo "pipeline complete"

test: ## Run test suite
	$(TEST_CMD)

clean: ## Remove caches and build artifacts (never touches data/raw)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	@echo "cleaned (data/raw preserved)"
