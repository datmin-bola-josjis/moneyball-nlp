# Pipeline entry points. See docs/PLAN-1WEEK.md §7 for the target layout.
#
# Target: `make pipeline` runs the whole thing, raw data to output.
# Stages are runnable individually so a failure is cheap to isolate.

# `python3` on Windows is a Microsoft Store alias that fails when run, so the
# interpreter is probed instead of assumed.
PYTHON ?= $(shell python3 -c "print(1)" >/dev/null 2>&1 && echo python3 || echo python)

.DEFAULT_GOAL := help
.PHONY: help setup check config population scrape scrape-verify scrape-pilot review review-score link nlp score viz pipeline test clean

# pytest is preferred, but the suite is plain unittest, so a machine where
# `make setup` has not run yet can still verify the code.
ifeq ($(shell $(PYTHON) -c "import pytest" >/dev/null 2>&1 && echo yes),yes)
TEST_CMD = $(PYTHON) -m pytest tests/ -q
else
TEST_CMD = $(PYTHON) -m unittest discover -s tests -t . $(if $(V),-v,)
endif

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies from requirements.txt
	$(PYTHON) -m pip install -r requirements.txt

check: config ## Validate config and run tests
	$(TEST_CMD)

config: ## Validate config/config.yaml parses and has expected shape
	$(PYTHON) -c "import yaml; d = yaml.safe_load(open('config/config.yaml')); assert len(d) == 11, f'expected 11 top-level keys, got {len(d)}'; print('config ok:', len(d), 'sections')"

# ---------------------------------------------------------------- Stages
# Each stage reads from data/ and writes to data/, never overwriting raw input.

population: ## Stage A - build player population and lock the text sample
	$(PYTHON) -m src.population.build

scrape: ## Stage B - retrieve texts per player (reddit, youtube, article)
	$(PYTHON) -m src.scrape.run

scrape-verify: ## Stage B Day 1 - verify configured subreddit names against Reddit
	$(PYTHON) -m src.scrape.run --verify

scrape-pilot: ## Stage B Day 2 - pilot scraping, PILOT=20 players by default
	$(PYTHON) -m src.scrape.run --pilot $(or $(PILOT),20)

review: ## Stage B Day 2 - draw 100 scraped texts for manual relevance labels
	$(PYTHON) -m src.scrape.run --sample $(if $(N),--n-sample $(N),)

review-score: ## Stage B - score the filled review sheet into reports/retrieval_relevance.md
	$(PYTHON) -m src.scrape.run --score

link: ## Stage C - entity linking and text filtering
	$(PYTHON) -m src.link.resolve

nlp: ## Stage D - sentiment and aspect extraction
	$(PYTHON) -m src.nlp.analyze

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
