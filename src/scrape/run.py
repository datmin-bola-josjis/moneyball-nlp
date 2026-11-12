"""Stage B entry point (`make scrape`, `make scrape-verify`, `make scrape-pilot`).

    python -m src.scrape.run --verify          # Day 1 gate: check subreddit names
    python -m src.scrape.run --pilot 20        # pilot on 20 mixed players
    python -m src.scrape.run                   # full run over the locked sample
    python -m src.scrape.run --sample          # draw texts for manual relevance review
    python -m src.scrape.run --score           # score the filled review sheet

Full runs refuse to start until the locked sample exists (AGENTS.md rule 14) so
scraping never quietly covers a different player list than the report claims.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import ROOT, load_config
from src.scrape import apify_reddit, relevance, subreddits
from src.scrape.aliases import AliasIndex
from src.scrape.players import DEFAULT_PLAYERS, load_players, market_values, pilot_subset
from src.scrape.reddit import run as run_reddit
from src.scrape.reddit_client import RedditClient

SAMPLE_FILE = ROOT / load_config()["text_sample"]["locked_file"]


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )


def _sample_players() -> list:
    """Players in the locked text sample; hard stop when it is missing."""
    if not SAMPLE_FILE.exists():
        raise SystemExit(
            f"locked text sample not found: {SAMPLE_FILE}\n"
            "Stage A (person A) locks data/processed/text_sample.parquet on Day 1; "
            "Stage B must not pick its own players."
        )
    if not load_config()["text_sample"].get("locked"):
        raise SystemExit(
            "text_sample.locked is false in config/config.yaml - the sample is not "
            "frozen yet, so scraping now would not be reproducible. Ask A to lock it."
        )
    return load_players(SAMPLE_FILE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage B: player-centric Reddit retrieval")
    parser.add_argument("--verify", action="store_true", help="check configured subreddit names")
    parser.add_argument("--pilot", type=int, metavar="N", help="run on N players spread by market value")
    parser.add_argument("--players", help=f"population file (default {DEFAULT_PLAYERS.name})")
    parser.add_argument("--sample", action="store_true", help="draw texts for manual relevance labelling")
    parser.add_argument("--score", action="store_true", help="score the filled relevance sheet")
    parser.add_argument("--tag", help="run tag to draw from, e.g. pilot20 (default: newest)")
    parser.add_argument("--n-sample", type=int, default=100, help="texts to draw for review")
    parser.add_argument(
        "--provider",
        choices=["oauth", "apify"],
        default="oauth",
        help="reddit retrieval path: oauth (default, ToS-compliant) or apify (marketplace actor)",
    )
    parser.add_argument(
        "--estimate-cost", action="store_true", help="print the apify cost estimate and exit"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.verify:
        results = subreddits.verify(RedditClient())
        path = subreddits.write_report(results)
        invalid = [name for name, ok in results.items() if not ok]
        print(f"subreddit check -> {path} ({len(results)} names, {len(invalid)} invalid)")
        return 1 if invalid else 0

    if args.sample:
        print(f"review sheet -> {relevance.sample_for_review(n=args.n_sample, tag=args.tag)}")
        return 0

    if args.score:
        path, stats = relevance.score_review()
        print(f"{path}: {stats['rate']:.1%} relevant on {stats['labelled']} labelled texts")
        return 0

    if args.estimate_cost:
        apify_cfg = load_config()["text_sources"]["reddit"]["apify"]
        chosen = (
            _sample_players()
            if args.players is None
            else load_players(args.players)
        )
        est = apify_reddit.estimate_cost(
            len(chosen),
            int(apify_cfg.get("max_posts_per_player", 10)),
            int(apify_cfg.get("max_comments_per_post", 100)),
        )
        print(
            f"apify estimate: {est['players']} players, ~{est['posts']} posts, "
            f"~{est['comments']} comments -> ${est['usd']:.2f} "
            f"(cap ${apify_cfg.get('max_cost_usd')})"
        )
        try:
            remaining = apify_reddit.ApifyClient().credit_remaining()
        except SystemExit:
            remaining = None  # no token configured; the estimate above still stands
        if remaining is not None:
            verdict = "ok" if est["usd"] <= remaining else "NOT ENOUGH CREDIT"
            print(f"apify credit remaining this cycle: ${remaining:.2f} -> {verdict}")
        return 0

    if args.pilot:
        population_path = args.players or DEFAULT_PLAYERS
        chosen = pilot_subset(
            load_players(population_path), args.pilot, market_values(population_path)
        )
        index = AliasIndex.build(chosen)
        logging.getLogger("pilot").info(
            "pilot players: %d, ambiguous aliases needing club context: %d",
            len(chosen), len(index.alias_debug()),
        )
        runner = apify_reddit.run if args.provider == "apify" else run_reddit
        runner(chosen, tag=f"pilot{args.pilot}")
        return 0

    runner = apify_reddit.run if args.provider == "apify" else run_reddit
    runner(_sample_players(), tag="full")
    return 0


if __name__ == "__main__":
    sys.exit(main())
