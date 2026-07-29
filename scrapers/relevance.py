"""Strict content-relevance validation — precision over volume.

The rule the whole tool hangs on: a keyword appearing in a page's related-links
footer, "trending" rail, share widget, or nav is NOT a relevant result. Before we
ever test for a relevance term we strip boilerplate/related-article blocks, so a term
that only appears in a "You may also like" list correctly fails the check.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Substrings in class/id that mark non-content blocks to strip before matching.
_BOILERPLATE_HINTS = [
    "related", "recommend", "more-", "morefrom", "trending", "popular", "sidebar",
    "footer", "nav", "menu", "share", "social", "comment", "promo", "newsletter",
    "subscribe", "advert", "ad-", "-ad", "sponsor", "read-more", "readmore",
    "outbrain", "taboola", "widget", "breadcrumb", "tags", "cookie",
]
_STRIP_TAGS = ["script", "style", "nav", "footer", "aside", "header", "form", "noscript"]


def extract_main_text(html: str) -> str:
    """Return the article's real body text, boilerplate removed.

    Uses BeautifulSoup. If an ``<article>`` / ``<main>`` element exists we prefer it;
    otherwise we strip known boilerplate containers from the whole document.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    # Drop any element whose class or id hints it is a non-content block. Collect
    # first, then decompose, so we never touch an element already detached by an
    # ancestor's removal (whose .attrs becomes None mid-iteration).
    to_remove = []
    for el in soup.find_all(True):
        if el.attrs is None:
            continue
        ident = " ".join(
            filter(None, [" ".join(el.get("class", []) or []), el.get("id", "") or "",
                          el.get("role", "") or ""])
        ).lower()
        if ident and any(hint in ident for hint in _BOILERPLATE_HINTS):
            to_remove.append(el)
    for el in to_remove:
        if el.attrs is not None:
            el.decompose()

    container = soup.find("article") or soup.find("main") or soup.body or soup
    if container is None:
        return ""
    # Collect paragraph-ish text.
    paras = [p.get_text(" ", strip=True) for p in container.find_all(["p", "h1", "h2", "li"])]
    text = "\n".join(p for p in paras if p)
    if not text.strip():
        text = container.get_text(" ", strip=True)
    return text.strip()


def first_paragraphs(html: str, max_paras: int = 4) -> str:
    """First few real paragraphs, used when a feed summary merely echoes the title."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    to_remove = []
    for el in soup.find_all(True):
        if el.attrs is None:
            continue
        ident = (" ".join(el.get("class", []) or []) + " " + (el.get("id", "") or "")).lower()
        if ident and any(hint in ident for hint in _BOILERPLATE_HINTS):
            to_remove.append(el)
    for el in to_remove:
        if el.attrs is not None:
            el.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    if container is None:
        return ""
    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paras = [p for p in paras if len(p) > 20]
    return "\n".join(paras[:max_paras]).strip()


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def contains_any_term(text: str, terms: List[str]) -> bool:
    """Case-insensitive OR match of any relevance term within text."""
    if not text:
        return False
    hay = _normalize(text)
    for term in terms:
        t = _normalize(term)
        if t and t in hay:
            return True
    return False


def matched_terms(text: str, terms: List[str]) -> List[str]:
    hay = _normalize(text)
    return [term for term in terms if _normalize(term) and _normalize(term) in hay]


def term_appears_anywhere(html: str, terms: List[str]) -> bool:
    """True if a term appears ANYWHERE on the raw page — including boilerplate/related-
    links/nav — as opposed to :func:`contains_any_term` on boilerplate-stripped text.

    This distinguishes two situations that both make ``validate_relevance`` return
    relevant=False, which matters for callers deciding whether a failed check means
    "confirmed junk" or "genuinely no mention at all":
      * term present only in a related-articles/footer/nav widget (confirmed junk —
        this IS the spec's core example: a footer mention is not a relevant result);
      * term absent from the page entirely, real content AND boilerplate alike (no
        signal either way from a keyword match — a candidate for semantic review
        elsewhere, not evidence of relevance OR irrelevance by itself).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return contains_any_term(soup.get_text(" ", strip=True), terms)


def validate_relevance(
    headline: str,
    terms: List[str],
    article_html: Optional[str] = None,
) -> dict:
    """Decide whether an article is relevant, and produce the text to store.

    Returns ``{"relevant": bool, "text": str, "matched_in": "headline"|"body"|None}``.

    Rule:
      1. If a term is in the headline -> relevant. Text = main body if fetched, else "".
      2. Else, if article HTML was fetched, strip boilerplate and test the *real*
         content. If a term appears in the real content -> relevant, store that text.
      3. Otherwise -> not relevant (drop).
    """
    if contains_any_term(headline, terms):
        body = extract_main_text(article_html) if article_html else ""
        return {"relevant": True, "text": body, "matched_in": "headline"}

    if article_html is not None:
        body = extract_main_text(article_html)
        if contains_any_term(body, terms):
            return {"relevant": True, "text": body, "matched_in": "body"}
        return {"relevant": False, "text": body, "matched_in": None}

    return {"relevant": False, "text": "", "matched_in": None}
