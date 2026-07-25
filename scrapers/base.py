"""Shared scraper contract.

Every channel exposes ``collect(cfg, params) -> ScrapeResult``. Scrapers are *pure
collectors*: they return items and errors but do NOT touch the DB. The runner
(jobs.run_collection) wraps a collect() call with start_run / save_items / finish_run,
so lineage and dedup are enforced identically for every channel and scrapers stay
trivially unit-testable with mocked network.

Honesty rule: a scraper NEVER fabricates items. On failure it appends a human-readable
string to ``errors`` and returns whatever partial results it did obtain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ScrapeResult:
    channel: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    # Optional per-source diagnostics (e.g. feed health), surfaced in the run log.
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def add(self, item: Dict[str, Any]) -> None:
        self.items.append(item)

    def error(self, msg: str) -> None:
        self.errors.append(msg)


def relevance_terms(cfg: Dict[str, Any]) -> List[str]:
    return [t for t in cfg.get("relevance_terms", []) if t]


def languages(cfg: Dict[str, Any]) -> List[str]:
    return cfg.get("market", {}).get("languages", ["en"]) or ["en"]
