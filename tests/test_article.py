"""Tests for the article collector.

No network. `robots` and `fetcher` are injected, which is why they are
parameters.

The rule that decides whether an article is about a player is
`min_name_mentions` (PRD §12), and an off-by-one there silently adds or removes
evidence, so both sides of the boundary are pinned. The other pinned behaviour
is that a disallowed `robots.txt` stops the fetch instead of being treated as an
inconvenience (AGENTS.md rule 12).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scrape import article
from src.scrape.article import (
    ArticleCandidate,
    RobotsCache,
    article_matches,
    count_name_mentions,
    records_from_article,
    split_paragraphs,
)
from src.scrape.players import Player

SAKA = Player(
    player_id="fotmob_1",
    name="Bukayo Saka",
    aliases=("Saka", "B. Saka"),
    club="Arsenal",
)

LONG_PARAGRAPH = (
    "Bukayo Saka was the outstanding player on the pitch for Arsenal across the "
    "entire second half and his movement created the opening goal."
)


def candidate(body: str, title: str = "", publisher: str = "theguardian.com") -> ArticleCandidate:
    return ArticleCandidate(
        url="https://theguardian.com/football/saka",
        title=title,
        publisher=publisher,
        published_at="2026-02-01T09:00:00+00:00",
        body=body,
    )


# ------------------------------------------------------------------- name count
def test_count_name_mentions_matches_whole_phrases_only() -> None:
    """"Saka" inside another word must not count; substring matching inflates it."""
    text = "Saka scored. Bukayo Saka again. Notasakamention here."

    assert count_name_mentions(text, SAKA) == 2


def test_count_name_mentions_is_case_insensitive() -> None:
    assert count_name_mentions("saka AND bUkAyO sAkA both appear here", SAKA) == 2


def test_count_name_mentions_handles_player_with_no_alias() -> None:
    bare = Player(player_id="x", name="Unknown Player", aliases=(), club="Chelsea")

    assert count_name_mentions("Unknown Player did nothing", bare) == 1


# --------------------------------------------------------------- article match
def test_title_mention_is_enough_even_with_empty_body() -> None:
    assert article_matches(candidate("", title="Saka rescues Arsenal"), SAKA, 3)


def test_body_below_the_threshold_is_rejected() -> None:
    """Boundary, low side: two mentions with min_name_mentions=3 must fail."""
    body = "Saka did well. Saka did well again."

    assert count_name_mentions(body, SAKA) == 2
    assert article_matches(candidate(body), SAKA, 3) is False


def test_body_at_the_threshold_is_accepted() -> None:
    """Boundary, exact side: three mentions with min_name_mentions=3 must pass."""
    body = "Saka did well. Saka did well. Saka did well."

    assert count_name_mentions(body, SAKA) == 3
    assert article_matches(candidate(body), SAKA, 3) is True


def test_threshold_of_one_accepts_a_single_mention() -> None:
    assert article_matches(candidate("Saka did well."), SAKA, 1) is True


def test_non_positive_threshold_is_treated_as_one() -> None:
    """A zero/negative config value must not mean "every article matches"."""
    assert article_matches(candidate("Saka did well."), SAKA, 0) is True
    assert article_matches(candidate("Nobody here."), SAKA, -5) is False


# ------------------------------------------------------------------- paragraphs
def test_split_paragraphs_keeps_blocks_and_leaves_length_to_config() -> None:
    """Splitting must not pre-filter: `min_words` from config owns that decision.

    If splitting dropped short blocks silently, `records_from_article` could
    never report *why* a paragraph was rejected, and the cleaning table would
    stop being reproducible from the run.
    """
    body = "Too short.\n" + LONG_PARAGRAPH + "\n\nAlso short."

    paragraphs = split_paragraphs(body)

    assert paragraphs == ["Too short.", LONG_PARAGRAPH, "Also short."]


def test_records_only_keep_paragraphs_that_name_the_player() -> None:
    body = LONG_PARAGRAPH + "\n\n" + (
        "Chelsea defended deep for the whole second half and never once looked "
        "like equalising despite having more of the ball."
    )

    records = records_from_article(candidate(body), SAKA, min_words=8, seen_hashes=set())

    assert len(records) == 1
    assert records[0].unit_type == "sentence", (
        "Stage D reads only `sentence`; PRD §8 does not list a paragraph type"
    )
    assert records[0].source == "article"
    assert records[0].channel == "theguardian.com"
    assert "Saka" in records[0].text_clean


def test_duplicate_paragraphs_across_articles_are_dropped() -> None:
    seen: set[str] = set()
    body = LONG_PARAGRAPH

    first = records_from_article(candidate(body), SAKA, 8, seen)
    second = records_from_article(
        candidate(body, publisher="bbc.co.uk"), SAKA, 8, seen, counters=(c := {})
    )

    assert len(first) == 1
    assert second == []
    assert c.get("dropped_article_duplicate") == 1


def test_short_paragraph_is_counted_and_dropped() -> None:
    records = records_from_article(
        candidate("Saka good"), SAKA, min_words=8, seen_hashes=set(), counters=(c := {})
    )

    assert records == []
    assert c.get("dropped_article_paragraph_too_short") == 1


# ---------------------------------------------------------------------- robots
def test_robots_disallow_blocks_the_fetch() -> None:
    cache = RobotsCache(
        fetch_text=lambda url: "User-agent: *\nDisallow: /football/"
    )

    assert cache.allowed("https://theguardian.com/football/saka") is False
    assert cache.allowed("https://theguardian.com/sport/saka") is True


def test_unreachable_robots_is_treated_as_disallow_all() -> None:
    """Rule 12: a robots.txt we cannot read is not permission to scrape."""

    def boom(url: str) -> str:
        raise RuntimeError("network down")

    cache = RobotsCache(fetch_text=boom)

    assert cache.allowed("https://example.com/anything") is False


def test_robots_is_fetched_once_per_host() -> None:
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return "User-agent: *\nAllow: /"

    cache = RobotsCache(fetch_text=fetch)
    cache.allowed("https://example.com/a")
    cache.allowed("https://example.com/b")

    assert calls == ["https://example.com/robots.txt"]


def test_robots_rejects_a_url_without_host() -> None:
    assert RobotsCache(fetch_text=lambda url: "").allowed("/relative/path") is False


# ------------------------------------------------------------------------- run
def test_run_refuses_when_the_source_is_disabled(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        article.run([SAKA], [candidate(LONG_PARAGRAPH)], cfg={"enabled": False})

    assert "disabled" in str(excinfo.value)


def test_run_refuses_when_stage_c_cannot_disambiguate_articles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 17 guard.

    `src/link/resolve.py` is an untracked Role D file, so a checkout may lack the
    `article` branch. Producing rows nothing filters would silently bypass the
    club-context check, so the collector must refuse instead. Point `ROOT` at an
    empty tree to simulate that checkout.
    """
    monkeypatch.setattr(article, "ROOT", tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        article.run([SAKA], [candidate(LONG_PARAGRAPH)], cfg={"enabled": True})

    assert "rule 17" in str(excinfo.value)
