"""Stage 2 — LLM analysis layer.

Batches unanalyzed items (12/batch) to the Claude API and writes one analysis row per
item. Claude reads all project languages natively; the one-line English summary is the
translation layer for reporting. Analysis is idempotent (an item is never re-tagged),
and failed batches are skippable/retryable — a crash mid-run never double-writes.

The model is configurable (default ``claude-haiku-4-5``); the key comes from env only.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

import storage
from settings import settings

BATCH_SIZE = 12

# Fixed vocabularies keep tags aggregatable. trend_category is the exception: it is
# SEEDED from the project's own trend terms plus an "other/emergent" catch-all — never
# a hard-coded trend list.
SENTIMENTS = ["positive", "negative", "neutral", "mixed"]
BRAND_FOCUS = ["target brand", "named competitor", "category-generic", "corporate", "unrelated"]


def _trend_categories(cfg: Dict[str, Any]) -> List[str]:
    seeds = [t for t in cfg.get("keywords", {}).get("trend_terms", []) if t]
    return seeds + ["other/emergent"]


def build_prompt(items: List[Dict[str, Any]], cfg: Dict[str, Any]) -> str:
    brand = cfg.get("product", {}).get("brand", "")
    competitors = cfg.get("competitors", [])
    category = cfg.get("product", {}).get("category", "")
    trend_cats = _trend_categories(cfg)
    languages = cfg.get("market", {}).get("languages", ["en"])

    lines = [
        "You are a market-research analyst tagging consumer/media text for a study.",
        f"Target brand: {brand or '(unspecified)'}",
        f"Named competitors: {', '.join(competitors) if competitors else '(none)'}",
        f"Product category: {category or '(unspecified)'}",
        f"Text may be in these languages: {', '.join(languages)}. Read them natively.",
        "",
        "For EACH numbered item, return an object with these fields:",
        '  sentiment: one of ["positive","negative","neutral","mixed"]',
        "  sentiment_score: float from -1.0 (very negative) to 1.0 (very positive)",
        "  language: ISO code of the item's language (e.g. en, zh, hi)",
        "  summary_en: a single concise English sentence summarizing the item (the translation layer)",
        "  rating_signal: any explicit rating found in the text (e.g. '4/5', '1 star') or null",
        "  purchase_driver: the main reason to buy/avoid mentioned (e.g. price, taste, availability) or null",
        "  usage_occasion: when/where the product is used, if mentioned, else null",
        f"  trend_category: one of {json.dumps(trend_cats)} (use 'other/emergent' if none fit)",
        f"  brand_focus: one of {json.dumps(BRAND_FOCUS)}",
        "  promo_mentioned: true/false — is a promotion/discount/offer mentioned?",
        "  emotion: dominant emotion (e.g. joy, anger, frustration, trust, neutral)",
        "",
        "Return ONLY a JSON array, one object per item, in the same order. No prose.",
        "",
        "ITEMS:",
    ]
    for i, it in enumerate(items):
        text = (it.get("text") or "").strip().replace("\n", " ")
        title = (it.get("title") or "").strip()
        lines.append(f"[{i}] source={it.get('source')} | title={title[:160]} | text={text[:1200]}")
    return "\n".join(lines)


def parse_response(text: str, n_items: int) -> List[Dict[str, Any]]:
    """Extract the JSON array of tag objects from the model response, robustly."""
    if not text:
        raise ValueError("Empty model response")
    # Grab the first top-level [...] block.
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON array in model response")
    blob = text[start:end + 1]
    data = json.loads(blob)
    if not isinstance(data, list):
        raise ValueError("Model response is not a JSON array")
    # Normalize length: pad/truncate defensively so indexing stays aligned.
    out: List[Dict[str, Any]] = []
    for i in range(n_items):
        tags = data[i] if i < len(data) and isinstance(data[i], dict) else {}
        out.append(_normalize_tags(tags))
    return out


def _normalize_tags(tags: Dict[str, Any]) -> Dict[str, Any]:
    sentiment = str(tags.get("sentiment", "neutral")).lower().strip()
    if sentiment not in SENTIMENTS:
        sentiment = "neutral"
    try:
        score = float(tags.get("sentiment_score"))
        score = max(-1.0, min(1.0, score))
    except (TypeError, ValueError):
        score = {"positive": 0.6, "negative": -0.6, "neutral": 0.0, "mixed": 0.0}[sentiment]
    return {
        "sentiment": sentiment,
        "sentiment_score": score,
        "language": tags.get("language"),
        "summary_en": tags.get("summary_en"),
        "rating_signal": tags.get("rating_signal"),
        "purchase_driver": tags.get("purchase_driver"),
        "usage_occasion": tags.get("usage_occasion"),
        "trend_category": tags.get("trend_category") or "other/emergent",
        "brand_focus": tags.get("brand_focus"),
        "promo_mentioned": bool(tags.get("promo_mentioned")),
        "emotion": tags.get("emotion"),
    }


def _default_call(prompt: str, model: str, max_tokens: int = 3000) -> str:
    from anthropic import Anthropic

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot run analysis.")
    client = Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def call_claude(prompt: str, model: Optional[str] = None, max_tokens: int = 3000) -> str:
    """Public one-shot Claude call reused by other modules (e.g. source discovery)."""
    return _default_call(prompt, model or settings.analysis_model, max_tokens=max_tokens)


def analyze_batch(project_id: int, *, batch_size: int = BATCH_SIZE,
                  call_fn: Optional[Callable[[str, str], str]] = None,
                  model: Optional[str] = None) -> Dict[str, Any]:
    """Analyze ONE batch of unanalyzed items. Idempotent + safe to retry."""
    project = storage.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    cfg = project["config"]
    model = model or settings.analysis_model
    call = call_fn or _default_call

    items = storage.get_unanalyzed_items(project_id, limit=batch_size)
    if not items:
        return {"analyzed": 0, "remaining": 0, "status": "empty"}

    prompt = build_prompt(items, cfg)
    try:
        raw = call(prompt, model)
        tags_list = parse_response(raw, len(items))
    except Exception as exc:
        # Failed batch: nothing written, item stays unanalyzed -> retryable.
        return {"analyzed": 0, "remaining": storage.count_unanalyzed(project_id),
                "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    written = 0
    for it, tags in zip(items, tags_list):
        if storage.save_analysis(project_id, it["id"], model, tags):
            written += 1
    storage.audit("analysis", f"batch analyzed {written} items with {model}", project_id=project_id)
    return {"analyzed": written, "remaining": storage.count_unanalyzed(project_id), "status": "ok",
            "model": model}


def analyze_all(project_id: int, *, max_batches: int = 1000,
                call_fn: Optional[Callable[[str, str], str]] = None,
                model: Optional[str] = None) -> Dict[str, Any]:
    """Analyze every unanalyzed item, batch by batch. Stops on the first hard error."""
    total = 0
    batches = 0
    for _ in range(max_batches):
        res = analyze_batch(project_id, call_fn=call_fn, model=model)
        if res["status"] == "empty":
            break
        if res["status"] == "error":
            return {"analyzed": total, "batches": batches, "status": "error", "error": res.get("error"),
                    "remaining": res.get("remaining")}
        total += res["analyzed"]
        batches += 1
        if res.get("remaining", 0) <= 0:
            break
        if res["analyzed"] == 0:
            break  # avoid infinite loop if items can't be tagged
    return {"analyzed": total, "batches": batches, "status": "ok",
            "remaining": storage.count_unanalyzed(project_id)}
