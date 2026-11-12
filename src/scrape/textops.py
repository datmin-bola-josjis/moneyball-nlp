"""Pure text helpers shared by the scrapers (Stage B) and dedupe in Stage C.

No I/O, no config reads: everything here is deterministic so it can be tested
directly. Cross-source dedupe relies on ``text_hash`` being stable, so C can
drop a YouTube comment that duplicates a Reddit one.
"""

from __future__ import annotations

import hashlib
import html
import re

_WHITESPACE = re.compile(r"\s+")
_MD_QUOTE = re.compile(r"^\s*>+\s?", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_NON_LATIN = re.compile(r"[\u0400-\u04FF\u0590-\u06FF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")

# Heuristic language gate. `ponytail:` ceiling - catches scripts and obvious
# non-English word order only, not Spanish/Portuguese text written in Latin
# script. Upgrade to `lingua`/`langdetect` if retrieval relevance lands < 85%
# in the pilot (PRD §11).
_STOPWORDS = frozenset(
    "a an the is are was were be been has have had he his him she her they them "
    "it its this that these those of in on at to for with from and or but not no "
    "you we i as by about into than then so if when who what very really just".split()
)

# Bot/spam markers. Author matching runs before the author is discarded, so no
# username is ever persisted (AGENTS.md rule 11).
_BOT_BODY = re.compile(
    r"\b(i am a bot|automoderator|this action was performed automatically|"
    r"i'm a bot|beep boop)\b",
    re.IGNORECASE,
)
_BOT_AUTHOR_SUFFIXES = ("bot", "automoderator", "-bot")


def clean_text(raw: str) -> str:
    """Strip markdown noise and normalise whitespace, keeping the words intact."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = _MD_QUOTE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = text.replace("*", "").replace("`", "")
    return _WHITESPACE.sub(" ", text).strip()


def text_hash(text_clean: str) -> str:
    """Stable dedupe key shared with the other text sources."""
    return hashlib.sha256(text_clean.lower().encode("utf-8")).hexdigest()[:16]


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def is_english(text: str) -> bool:
    if not text or _NON_LATIN.search(text):
        return False
    words = [w.lower() for w in _WORD.findall(text)]
    if len(words) < 3:
        return False
    return sum(w in _STOPWORDS for w in words) > 0


def is_bot_like(author: str, body: str) -> bool:
    name = (author or "").lower()
    return name.endswith(_BOT_AUTHOR_SUFFIXES) or bool(_BOT_BODY.search(body or ""))


def split_sentences(text_clean: str) -> list[str]:
    """Split one cleaned comment into sentences, dropping fragments under 3 words.

    Stage D scores at sentence level (PRD §8 `unit_type`), so a three-word
    fragment ("Yes.", "This.") is not evidence and is dropped here.
    """
    parts = _SENTENCE_SPLIT.split(text_clean)
    return [p.strip() for p in parts if word_count(p) >= 3]
