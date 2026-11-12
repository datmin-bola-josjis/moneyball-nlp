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
            f"missing {name} in .env - copy .env.example, fill the Reddit app "
            "credentials, then rerun. Stage B cannot run without them."
        )
    return value


def out_path(*parts: str) -> Path:
    """Absolute path under the repository, parent directories created."""
    path = ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
