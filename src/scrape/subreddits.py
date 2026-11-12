"""Subreddit name verification (Day 1 gate from config/config.yaml).

Reddit answers 403 to unauthenticated callers, so a plain `curl` proves nothing.
Names are checked here against the authenticated `/r/<name>/about` endpoint and
the result is written to `data/interim/subreddit_check.json`, because a wrong
name means silent empty scraping.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.config import ROOT, load_config
from src.scrape.reddit_client import RedditClient, RedditError

log = logging.getLogger("reddit.verify")
REPORT = ROOT / "data" / "interim" / "subreddit_check.json"


def configured_subreddits() -> list[str]:
    cfg = load_config()["text_sources"]["reddit"]
    names = list(cfg.get("subreddits_league", []))
    for group in cfg.get("subreddits_clubs", {}).values():
        names.extend(group)
    seen: dict[str, None] = {}
    for name in names:
        seen.setdefault(name, None)
    return list(seen)


def verify(client: RedditClient, names: list[str] | None = None) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name in names or configured_subreddits():
        try:
            results[name] = client.subreddit_exists(name)
        except RedditError as exc:
            log.error("verification failed for r/%s: %s", name, exc)
            results[name] = False
        status = "ok" if results[name] else "MISSING"
        log.info("r/%-22s %s", name, status)
    return results


def write_report(results: dict[str, bool], path: Path = REPORT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked": len(results),
        "valid": sorted(n for n, ok in results.items() if ok),
        "invalid": sorted(n for n, ok in results.items() if not ok),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    client = RedditClient()
    results = verify(client)
    path = write_report(results)
    invalid = [n for n, ok in results.items() if not ok]
    print(f"checked {len(results)} subreddits, report: {path}")
    if invalid:
        # Config is the single source of truth: fix names there, not in code.
        print("invalid names (fix config/config.yaml, then rerun):", ", ".join(invalid))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
