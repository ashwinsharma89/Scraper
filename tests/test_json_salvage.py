"""Shared truncated-JSON salvage parser (extracted from outlet_discovery.py once
site_intelligence.py needed the exact same fallback for the exact same reason)."""
import json_salvage as js


def test_extracts_every_complete_object_before_a_truncation_point():
    truncated = """{"outlets": [
        {"name": "A", "domain": "a.com"},
        {"name": "B", "domain": "b.com"},
        {"name": "C", "domain":"""
    objs = js.extract_balanced_objects(truncated)
    assert [o["name"] for o in objs] == ["A", "B"]


def test_does_not_get_confused_by_the_outer_wrapper_object():
    """The very first '{' is the OUTER {"outlets": [...]} wrapper, which never closes
    in a truncated response -- a naive single global depth counter never returns to
    0 and finds nothing (the exact real bug this function was built to fix)."""
    truncated = '{"outlets": [{"name": "A", "domain": "a.com"}'
    objs = js.extract_balanced_objects(truncated)
    assert len(objs) == 1 and objs[0]["name"] == "A"


def test_skips_objects_missing_the_required_key():
    text = '{"meta": {"count": 1}} {"name": "A", "domain": "a.com"}'
    objs = js.extract_balanced_objects(text)
    assert len(objs) == 1 and objs[0]["name"] == "A"


def test_required_key_is_configurable():
    text = '{"domain": "a.com", "title": "A"}'
    assert js.extract_balanced_objects(text, required_key="title") == [
        {"domain": "a.com", "title": "A"}]
    assert js.extract_balanced_objects(text, required_key="name") == []


def test_returns_empty_list_for_completely_unsalvageable_text():
    assert js.extract_balanced_objects('{"name": "A", "domain":') == []


def test_nested_quoted_braces_do_not_break_depth_tracking():
    text = '{"name": "A {weird} name", "domain": "a.com"}'
    objs = js.extract_balanced_objects(text)
    assert objs == [{"name": "A {weird} name", "domain": "a.com"}]
