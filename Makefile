# Pipeline entry points. See docs/PLAN-1WEEK.md §7 for the target layout.
#
# Target: `make pipeline` runs the whole thing, raw data to output.
# Stages are runnable individually so a failure is cheap to isolate.

PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help setup check config sample population scrape link nlp score viz pipeline test clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies from requirements.txt
	$(PYTHON) -m pip install -r requirements.txt

check: config ## Validate config and run tests
	$(PYTHON) -m pytest tests/ -q

config: ## Validate config/config.yaml parses and keeps its invariants
	$(PYTHON) -m src.validate_config

# ---------------------------------------------------------------- Stages
# Each stage reads from data/ and writes to data/, never overwriting raw input.

population: ## Stage A - build player population and lock the text sample
	$(PYTHON) -m src.population.build

scrape: ## Stage B - retrieve texts per player (reddit, youtube, article)
	$(PYTHON) -m src.scrape.run

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
	$(PYTHON) -m pytest tests/ -v

clean: ## Remove caches and build artifacts (never touches data/raw)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	@echo "cleaned (data/raw preserved)"
