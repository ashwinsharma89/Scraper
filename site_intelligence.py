"""AI-driven site discovery with a persistent, cross-project learning ledger.

DESIGN_01_category-discovery.md §4b. This is deliberately a DIFFERENT concern from
`outlet_discovery.py`: that module finds outlets whose NAME should count as market-relevance
evidence for one project's `market_terms`. This module answers a different question — "which
real websites are actually good sources of content for this category" — and, unlike every
other suggestion module in this codebase, remembers the answer ACROSS projects instead of
re-deriving it from scratch every time.

The loop:
  1. Before asking the LLM anything, check the global `site_intelligence` ledger (storage.py)
     for domains already known to be good for this category, from real past outcomes.
  2. Ask the LLM for fresh candidates anyway — the ledger is a cache/accelerant, not a ceiling;
     new real sites exist and should keep surfacing.
  3. Anything not already validated in the ledger is flagged `needs_validation: true` — this is
     the literal "can get manually validated if not sure" mechanism. A domain the ledger
     already has real track record for (some `times_used`) or a human has explicitly validated
     is shown pre-trusted instead.
  4. confirm_sites() is the ONLY place anything is written — matching every other suggestion
     module's "nothing until confirmed" contract (source_discovery.py, term_expansion.py,
     outlet_discovery.py all share this shape).
  5. record_outcomes() is called separately, after a REAL collection run, with the actual
     kept/dropped/blocked counts for each site that was used — this is what makes the ledger
     reflect reality instead of a one-time guess, and is not exercised until a real pilot runs.

Category matching is intentionally exact-string for now (DESIGN_01 §4b names the fragmentation
risk explicitly rather than building unproven normalization ahead of evidence).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

CAP = 40
# Real gap found live (user report: a single unconstrained LLM query returned ~180 real,
# correct Indian food/lifestyle sites; this tool's own CAP was hard-limiting every call
# to 20, regardless of what the model could actually produce). Raised to 40 — a
# meaningful jump, not the full ~180: the larger a single-call list gets, the more an
# LLM's confidence in "REAL, well-known" degrades toward its tail, and every candidate
# here is still independently reachability-probed before being trusted either way (see
# app.py's /api/discovery/sites), so a wrong domain from a larger list is caught, not
# silently trusted. 40 sites x ~110-130 tokens/object (name+domain+source_type+why+JSON
# punctuation) sized MAX_TOKENS below with real headroom, same sizing math
# outlet_discovery.py already validated live for its own CAP raise.
MAX_TOKENS = 5000
# A domain with fewer real uses than this is shown with its track record but still flagged
# needs_validation — a couple of lucky/unlucky runs isn't enough history to fully trust yet.
MIN_USES_TO_AUTO_TRUST = 3
MIN_CONFIDENCE_TO_AUTO_TRUST = 0.5


def _domain_of(url_or_domain: str) -> str:
    """Real bug found live (discovered verifying the CAP raise above against a real
    Claude call): str.lstrip("www.") strips a SET of characters ('w' and '.'), not
    the literal 4-char prefix -- it silently ate the real leading "w" off domains
    that legitimately start with one right where "www." would be (confirmed live:
    "whiskaffair.com" -> "hiskaffair.com", a real, correct domain corrupted into a
    wrong one on every request). startswith()+slice only strips an ACTUAL "www."
    prefix, matching the correct pattern analytics.py's items_by_domain() already
    uses."""
    s = (url_or_domain or "").strip().lower()
    if "://" in s:
        s = urlparse(s).netloc
    if s.startswith("www."):
        s = s[4:]
    return s


def _where(geo_scope: Optional[Dict[str, Any]]) -> str:
    geo_scope = geo_scope or {}
    level = geo_scope.get("level", "")
    value = geo_scope.get("value", "")
    country = geo_scope.get("country", "")
    return f"{value} ({level}, {country})" if value and level else (country or "an unspecified market")


def build_prompt(category: str, geo_scope: Optional[Dict[str, Any]] = None,
                 source_type_hint: Optional[str] = None) -> str:
    where = _where(geo_scope)
    # source_type_hint (e.g. "lifestyle & food blogs", "forums") scopes the search to ONE
    # genre instead of a single blended list across every genre at once — asked for
    # explicitly: a category-wide call tends to return mostly mainstream news outlets
    # (the most "famous" sites for a topic), crowding out the smaller, more specific
    # sites (food blogs, hobbyist forums) that a genre-scoped search surfaces instead.
    focus = (f'Focus specifically on "{source_type_hint}" — real sites of exactly that '
            f'kind, not news outlets in general.' if source_type_hint else
            "This includes news, lifestyle/blog, business, and any other editorial site "
            "genuinely relevant to this category and market — not just one type.")

    return "\n".join([
        f'You are identifying REAL, well-known websites that are good sources of content for '
        f'the category "{category}", specific to {where}.',
        "",
        focus,
        "Prefer sites a person actually reading about this category in this market would "
        "recognize — including smaller/specialist sites a person deep in this topic would "
        "know, not only the single most famous mainstream outlet.",
        "",
        "Return ONLY a JSON object with this key:",
        '  "sites": [ {"name": "<real display name>", "domain": "<real base domain, e.g. '
        '\\"scoopwhoop.com\\">", "source_type": "<e.g. news, lifestyle, business, forum>", '
        f'"why": "<one short reason>"}} ] — up to {CAP}, most relevant/well-known first',
        "",
        "Rules:",
        "- Every site must be REAL — do not invent a name or guess at a domain you are not "
        "confident about.",
        "- No commentary outside the JSON.",
    ])


def build_similar_sites_prompt(seed_domain: str, category: str,
                               geo_scope: Optional[Dict[str, Any]] = None) -> str:
    """"Sites like X" — a human just confirmed real interest in one specific site; find
    others of the same genre/audience rather than re-running the generic category search."""
    where = _where(geo_scope)
    return "\n".join([
        f'A market-research study is collecting content about "{category}" in {where}, and '
        f'has confirmed "{seed_domain}" as a genuinely good, real source.',
        "",
        f'Name other REAL websites SIMILAR to "{seed_domain}" — same genre, audience, and '
        f'general kind of content (e.g. if it is a mainstream national newspaper, find other '
        f'mainstream national newspapers; if it is a youth-culture/lifestyle blog, find other '
        f'youth-culture/lifestyle blogs) — specific to this category and market.',
        "",
        "Return ONLY a JSON object with this key:",
        '  "sites": [ {"name": "<real display name>", "domain": "<real base domain>", '
        '"source_type": "<e.g. news, lifestyle, business, forum>", '
        f'"why": "<one short reason it is similar to {seed_domain}>"}} ] — up to {CAP}, '
        "most similar/well-known first",
        "",
        "Rules:",
        f'- Do NOT include "{seed_domain}" itself in the results.',
        "- Every site must be REAL — do not invent a name or guess at a domain you are not "
        "confident about.",
        "- No commentary outside the JSON.",
    ])


def parse_sites(text: str) -> List[Dict[str, str]]:
    if not text:
        raise ValueError("Empty model response")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object in model response")

    try:
        data = json.loads(text[start:end + 1])
        raw_sites = data.get("sites") or []
    except json.JSONDecodeError:
        # Whole response isn't valid JSON — most commonly a max_tokens cutoff mid-
        # object (a real risk now that CAP/MAX_TOKENS were raised — see their
        # docstring). Salvage whatever complete site objects exist rather than
        # losing all of them, the same fix outlet_discovery.py already proved live.
        from json_salvage import extract_balanced_objects
        raw_sites = extract_balanced_objects(text)
        if not raw_sites:
            raise ValueError("Model response was not valid JSON and no site objects "
                             "could be salvaged from it")

    sites: List[Dict[str, str]] = []
    seen_domains = set()
    for s in raw_sites[:CAP]:
        if not isinstance(s, dict):
            continue
        domain = _domain_of(s.get("domain") or "")
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)
        sites.append({
            "name": str(s.get("name") or domain).strip(),
            "domain": domain,
            "source_type": str(s.get("source_type") or "").strip(),
            "why": str(s.get("why") or "").strip(),
        })
    return sites


def _merge_with_ledger(category: str, fresh: List[Dict[str, str]],
                       include_known: bool = True,
                       exclude_domains: Optional[set] = None) -> List[Dict[str, Any]]:
    """Shared by discover_sites() and find_similar_sites(): known ledger sites (with
    real track record) plus fresh LLM candidates not already covered, each tagged with
    its trust state. `include_known=False` skips listing every known ledger site up
    front (used by find_similar_sites, which is about NEW candidates around one seed,
    not a full category re-listing) but still enriches fresh candidates that happen
    to already be in the ledger.
    """
    import storage

    exclude_domains = exclude_domains or set()
    known_rows = storage.list_site_intelligence(category)
    known_by_domain = {r["domain"]: r for r in known_rows}

    results: List[Dict[str, Any]] = []
    seen = set(exclude_domains)

    if include_known:
        # Known sites first, most-confident already (list_site_intelligence's own order).
        for row in known_rows:
            if row["domain"] in seen:
                continue
            trusted = (
                row["validated_by_human"]
                or (row["times_used"] >= MIN_USES_TO_AUTO_TRUST
                    and (row["confidence"] or 0) >= MIN_CONFIDENCE_TO_AUTO_TRUST)
            )
            results.append({
                "name": row["name"] or row["domain"],
                "domain": row["domain"],
                "source_type": row["source_type"] or "",
                "why": f"Known from {row['times_used']} prior use(s)" if row["times_used"] else
                       "Previously suggested, not yet used",
                "known": True,
                "times_used": row["times_used"],
                "confidence": row["confidence"],
                "validated_by_human": bool(row["validated_by_human"]),
                "needs_validation": not trusted,
            })
            seen.add(row["domain"])

    # Fresh LLM candidates not already covered.
    for site in fresh:
        if site["domain"] in seen:
            continue
        seen.add(site["domain"])
        prior = known_by_domain.get(site["domain"])  # e.g. suggested before but never used
        results.append({
            **site,
            "known": prior is not None,
            "times_used": prior["times_used"] if prior else 0,
            "confidence": prior["confidence"] if prior else None,
            "validated_by_human": bool(prior and prior["validated_by_human"]),
            "needs_validation": not (prior and prior["validated_by_human"]),
        })

    return results


def discover_sites(category: str, geo_scope: Optional[Dict[str, Any]] = None,
                   source_type_hint: Optional[str] = None,
                   call_fn: Optional[Callable[[str, str], str]] = None,
                   model: Optional[str] = None) -> Dict[str, Any]:
    """Merge the ledger's known-good sites for this category with fresh LLM candidates.
    Read-only — nothing is written to the ledger here; see confirm_sites().

    `source_type_hint` (e.g. "lifestyle & food blogs", "forums") scopes the LLM search to
    one genre — pass it once per source type the wizard's step 4 confirmed, rather than
    one blended call, so smaller/specialist sites aren't crowded out by mainstream news.
    """
    from settings import settings

    category = (category or "").strip()
    if not category:
        raise ValueError("A category is required to discover sites.")

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=MAX_TOKENS))
    prompt = build_prompt(category, geo_scope, source_type_hint)
    raw = call(prompt, model or settings.analysis_model)
    fresh = parse_sites(raw)

    results = _merge_with_ledger(category, fresh, include_known=True)
    return {
        "category": category,
        "source_type_hint": source_type_hint,
        "sites": results,
        "_summary": {
            "total": len(results),
            "known": sum(1 for r in results if r["known"]),
            "needs_validation": sum(1 for r in results if r["needs_validation"]),
        },
    }


def find_similar_sites(seed_domain: str, category: str,
                       geo_scope: Optional[Dict[str, Any]] = None,
                       call_fn: Optional[Callable[[str, str], str]] = None,
                       model: Optional[str] = None) -> Dict[str, Any]:
    """"Sites like X" — asked for explicitly: confirming one real site (e.g.
    hindustantimes.com) should make it easy to find more of the same genre (toi.com,
    indianexpress.com, ...) without re-running the whole category search. Read-only,
    same contract as discover_sites(): nothing written here, confirm_sites() still the
    only write path.
    """
    from settings import settings

    seed_domain = _domain_of(seed_domain)
    category = (category or "").strip()
    if not seed_domain:
        raise ValueError("A seed domain is required.")
    if not category:
        raise ValueError("A category is required.")

    call = call_fn or (lambda p, m: __import__("analysis").call_claude(p, m, max_tokens=MAX_TOKENS))
    prompt = build_similar_sites_prompt(seed_domain, category, geo_scope)
    raw = call(prompt, model or settings.analysis_model)
    fresh = [s for s in parse_sites(raw) if s["domain"] != seed_domain]

    results = _merge_with_ledger(category, fresh, include_known=False,
                                 exclude_domains={seed_domain})
    return {
        "seed_domain": seed_domain, "category": category, "sites": results,
        "_summary": {"total": len(results),
                    "needs_validation": sum(1 for r in results if r["needs_validation"])},
    }


def confirm_sites(category: str, domains: List[str]) -> Dict[str, Any]:
    """User-confirmed subset of discover_sites()'s output. Records each as seen (increments
    times_suggested, creating the ledger row on first sight) and marks it human-validated —
    this is the only place discover_sites()'s output gets written anywhere."""
    import storage

    category = (category or "").strip()
    if not category:
        raise ValueError("A category is required.")

    confirmed = []
    for d in domains or []:
        domain = _domain_of(d)
        if not domain:
            continue
        storage.upsert_site_seen(domain, category)
        storage.mark_site_validated(domain, category)
        confirmed.append(domain)
    return {"confirmed": confirmed, "count": len(confirmed)}


def record_outcomes(category: str, outcomes: List[Dict[str, Any]]) -> None:
    """Call after a REAL collection run with each used site's actual results, e.g.
    outcomes = [{"domain": "scoopwhoop.com", "kept": 8, "dropped": 2, "blocked": False}, ...].
    This is what makes the ledger reflect reality instead of a one-time LLM guess — not
    exercised until a real pilot run produces real outcomes to feed back in."""
    import storage

    category = (category or "").strip()
    if not category:
        raise ValueError("A category is required.")
    for o in outcomes or []:
        domain = _domain_of(o.get("domain") or "")
        if not domain:
            continue
        storage.record_site_outcome(
            domain, category,
            kept=int(o.get("kept", 0)), dropped=int(o.get("dropped", 0)),
            blocked=bool(o.get("blocked", False)),
        )
