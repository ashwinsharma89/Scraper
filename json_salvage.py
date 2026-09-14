"""Salvage complete JSON objects from a possibly-truncated LLM response.

Extracted from outlet_discovery.py (where this was found and fixed live: an earlier
CAP/max_tokens combination truncated the model's response mid-object) into a shared
module once site_intelligence.py needed the exact same fallback for the exact same
reason (raising its own CAP made truncation a real risk there too) — one proven
implementation, not two copies to keep in sync.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


def extract_balanced_objects(text: str, required_key: str = "name") -> List[Dict[str, Any]]:
    """Try every '{' in the text as a possible object start and parse the substring up to
    its own matching '}', skipping any that fail. Used as a fallback when the whole
    response isn't valid JSON (e.g. cut off mid-object by a max_tokens limit) — this
    salvages every item that WAS completed before the cutoff instead of discarding all
    of them over one incomplete trailing object.

    Deliberately does NOT track depth globally from the start of the text — the very
    first '{' is the OUTER wrapper object (e.g. {"outlets": [...]}), which never closes
    in a truncated response, so a single global depth counter never returns to 0 and
    finds nothing (confirmed live: an earlier version had exactly that bug and silently
    extracted zero objects from a genuinely-salvageable response). Instead, each '{'
    gets its OWN independent attempt at finding a match; one that runs off the end of
    the text without closing is simply skipped, and the next '{' (e.g. the first real
    item object) is tried on its own terms.

    `required_key` filters parsed objects to ones that look like the expected item shape
    (every caller's items are keyed by "name" today) rather than accidentally matching
    unrelated nested objects.
    """
    objects: List[Dict[str, Any]] = []
    n = len(text)
    i = 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        closed_at = None
        j = i
        while j < n:
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        closed_at = j
                        break
            j += 1
        if closed_at is not None:
            try:
                obj = json.loads(text[i:closed_at + 1])
                if isinstance(obj, dict) and required_key in obj:
                    objects.append(obj)
            except json.JSONDecodeError:
                pass  # malformed candidate — skip, don't fail the whole batch over it
        i += 1  # advance by 1, not past the close — lets a nested '{' be tried too
    return objects
