"""Decision-grade data guarantees: dedup, lineage, project isolation, migrations."""
import storage
import migrations


def _item(link, title="T", text="body text here", source="news"):
    return {"link": link, "title": title, "text": text}


def test_cross_run_dedup_never_inflates(fresh_db):
    pid = storage.create_project("P", {})
    # Run 1 collects two items.
    r1 = storage.start_run(pid, "news", {})
    res1 = storage.save_items(pid, r1, "news", [_item("a"), _item("b")])
    storage.finish_run(r1, rows_returned=res1["returned"], rows_new=res1["new"],
                       rows_duplicate=res1["duplicate"])
    assert res1 == {"returned": 2, "new": 2, "duplicate": 0}

    # Run 2 re-collects the same two -> both duplicates, nothing stored again.
    r2 = storage.start_run(pid, "news", {})
    res2 = storage.save_items(pid, r2, "news", [_item("a"), _item("b")])
    storage.finish_run(r2, rows_returned=res2["returned"], rows_new=res2["new"],
                       rows_duplicate=res2["duplicate"])
    assert res2 == {"returned": 2, "new": 0, "duplicate": 2}

    # Total item count stayed at 2 -> counts are not inflated by duplicates.
    assert storage.count_items_by_source(pid) == {"news": 2}


def test_lineage_recorded(fresh_db):
    pid = storage.create_project("P", {})
    r1 = storage.start_run(pid, "news", {"query": "x"})
    storage.save_items(pid, r1, "news", [_item("a")])
    items = storage.list_items(pid)
    assert len(items) == 1
    # Every item carries the run that produced it.
    assert items[0]["run_id"] == r1
    assert items[0]["project_id"] == pid
    run = storage.get_run(r1)
    assert run["channel"] == "news"
    assert '"query": "x"' in run["params_json"]


def test_project_isolation_same_hash_both_stored(fresh_db):
    """Same content hash in two projects -> both rows exist (isolation)."""
    p1 = storage.create_project("P1", {})
    p2 = storage.create_project("P2", {})
    h = storage.compute_content_hash("news", "http://x", "Same Title", "Same body")
    r1 = storage.start_run(p1, "news", {})
    r2 = storage.start_run(p2, "news", {})
    it = {"link": "http://x", "title": "Same Title", "text": "Same body"}
    res1 = storage.save_items(p1, r1, "news", [it])
    res2 = storage.save_items(p2, r2, "news", [it])
    assert res1["new"] == 1 and res2["new"] == 1
    # Identical hash across the two projects.
    i1 = storage.list_items(p1)[0]
    i2 = storage.list_items(p2)[0]
    assert i1["content_hash"] == i2["content_hash"] == h
    # But each project sees exactly one item.
    assert len(storage.list_items(p1)) == 1
    assert len(storage.list_items(p2)) == 1


def test_content_hash_ignores_project(fresh_db):
    h1 = storage.compute_content_hash("news", "L", "Ti", "Body")
    h2 = storage.compute_content_hash("news", "L", "Ti", "Body")
    assert h1 == h2  # deterministic, project-independent


def test_migrations_idempotent(fresh_db):
    # Already migrated by the fixture; re-applying is a no-op and stays at latest.
    with storage.get_conn() as conn:
        assert migrations.current_version(conn) == migrations.latest_version()
        again = migrations.apply_migrations(conn)
        assert again == migrations.latest_version()


def test_purge_removes_project(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [_item("a")])
    storage.delete_project(pid)
    assert storage.get_project(pid) is None
    assert storage.list_items(pid) == []
