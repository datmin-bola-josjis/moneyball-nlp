"""Loader for the project's single config file (AGENTS.md rule 13).

League, season, whitelist, quotas and thresholds live in ``config/config.yaml``
only. Credentials live in ``.env`` only. Nothing here has a hardcoded default
that would silently change project behaviour.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


def env(name: str) -> str:
    """Read a required credential; fail loudly instead of scraping anonymously."""
    load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"missing {name} in .env.\n"
            "Reddit closed self-service app creation in Nov 2025 - opening "
            "https://www.reddit.com/prefs/apps only redirects to the Responsible "
            "Builder Policy. Data API access is now a manual request:\n"
            "  https://support.reddithelp.com/hc/en-us/requests/new"
            "?ticket_form_id=14868593862164\n"
            "See docs/tahap-b-reddit.md for the answers to paste and the fallback plan."
        )
    return value


def out_path(*parts: str) -> Path:
    """Absolute path under the repository, parent directories created."""
    path = ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
