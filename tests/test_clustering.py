"""Near-duplicate / syndicated-story clustering: groups reprints without deleting data."""
import storage
import analytics


def _item(title, link, published, text="body text here", source="news"):
    return {"title": title, "link": link, "published": published, "text": text}


def test_syndicated_titles_same_day_cluster_together(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Maggi price rises in KL - NST Online", "http://a", "2026-03-01"),
        _item("Maggi price rises in KL - The Star", "http://b", "2026-03-01"),
        _item("Maggi price rises in KL | Bernama", "http://c", "2026-03-02"),  # +1 day, still in window
    ])
    items = storage.list_items(pid)
    cluster_ids = {i["cluster_id"] for i in items}
    assert len(cluster_ids) == 1, "same story across outlets/near dates should share one cluster"
    # Nothing was deleted or merged — all 3 rows still exist with their own lineage.
    assert len(items) == 3
    assert {i["link"] for i in items} == {"http://a", "http://b", "http://c"}


def test_different_stories_get_different_clusters(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Maggi price rises in KL", "http://a", "2026-03-01"),
        _item("Nestle opens new factory in Selangor", "http://b", "2026-03-01"),
    ])
    items = storage.list_items(pid)
    assert len({i["cluster_id"] for i in items}) == 2


def test_recurring_annual_headline_far_apart_does_not_cluster(fresh_db):
    """Templated PR headlines (same wording, different years) must NOT merge just
    because the title matches — the date window prevents false clustering."""
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("MAGGI Cooking Competition Returns", "http://2025", "2025-05-01"),
        _item("MAGGI Cooking Competition Returns", "http://2026", "2026-05-01"),
    ])
    items = storage.list_items(pid)
    assert len({i["cluster_id"] for i in items}) == 2, "a year apart -> distinct events, not syndication"


def test_chained_syndication_all_join_one_cluster(fresh_db):
    """A matches B, then C matches B -> A, B, C all resolve to the same cluster."""
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Nestle sources 100 percent local chilli for Maggi", "http://a", "2026-04-10"),
        _item("Nestle sources 100 percent local chilli for Maggi - NST", "http://b", "2026-04-10"),
        _item("Nestle sources 100 percent local chilli for Maggi | Star", "http://c", "2026-04-11"),
    ])
    items = storage.list_items(pid)
    assert len({i["cluster_id"] for i in items}) == 1


def test_no_published_date_stays_singleton(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Maggi undated item one", "http://a", None),
        _item("Maggi undated item one", "http://b", None),
    ])
    items = storage.list_items(pid)
    # No date -> can't safely bound comparison -> each stays its own cluster.
    assert len({i["cluster_id"] for i in items}) == 2


def test_analytics_reports_total_stories_and_syndication_ratio(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Maggi price rises in KL - NST", "http://a", "2026-03-01"),
        _item("Maggi price rises in KL - Star", "http://b", "2026-03-01"),
        _item("Maggi price rises in KL - Bernama", "http://c", "2026-03-01"),
        _item("Different unrelated Maggi story", "http://d", "2026-03-15"),
    ])
    d = analytics.dashboard(pid)
    assert d["total_items"] == 4
    assert d["total_stories"] == 2  # 3 reprints -> 1 story, + 1 unrelated -> 1 story
    assert d["syndication_ratio"] == 0.5
    # count_unique_stories matches dashboard.
    assert storage.count_unique_stories(pid) == 2


def test_cluster_sizes_reflects_syndication_count(fresh_db):
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Maggi price rises in KL - NST", "http://a", "2026-03-01"),
        _item("Maggi price rises in KL - Star", "http://b", "2026-03-01"),
        _item("Standalone Maggi story", "http://c", "2026-03-20"),
    ])
    sizes = storage.cluster_sizes(pid)
    assert sorted(sizes.values()) == [1, 2]


def test_legacy_rows_with_null_cluster_id_count_correctly(fresh_db):
    """Rows written before this feature existed have cluster_id=NULL. SQL's
    COUNT(DISTINCT cluster_id) does not count NULLs at all, which would silently
    undercount them. count_unique_stories/cluster_sizes must fall back to treating
    each such row as its own singleton (via COALESCE(cluster_id, id))."""
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [
        _item("Legacy item one", "http://a", "2026-01-01"),
        _item("Legacy item two", "http://b", "2026-01-05"),
        _item("Legacy item three", "http://c", "2026-01-10"),
    ])
    # Simulate "legacy": wipe cluster_id as if these rows predate the migration.
    with storage.write_conn() as conn:
        conn.execute("UPDATE items SET cluster_id=NULL WHERE project_id=?", (pid,))

    assert storage.count_unique_stories(pid) == 3  # NOT 0 or 1 (the NULL-collapse bug)
    sizes = storage.cluster_sizes(pid)
    assert sorted(sizes.values()) == [1, 1, 1]
    d = analytics.dashboard(pid)
    assert d["total_stories"] == 3


def test_new_item_clusters_correctly_against_legacy_null_row(fresh_db):
    """A new (post-feature) item that near-duplicates an old legacy row (cluster_id=NULL,
    inserted before this feature existed) must still resolve to ONE shared story via the
    COALESCE(cluster_id, id) convention used consistently at both write and read time."""
    pid = storage.create_project("P", {})
    r = storage.start_run(pid, "news", {})
    storage.save_items(pid, r, "news", [_item("Maggi price rises in KL", "http://legacy", "2026-03-01")])
    with storage.write_conn() as conn:
        conn.execute("UPDATE items SET cluster_id=NULL WHERE project_id=?", (pid,))

    storage.save_items(pid, r, "news", [_item("Maggi price rises in KL - NST", "http://new", "2026-03-01")])

    assert storage.count_unique_stories(pid) == 1
    sizes = storage.cluster_sizes(pid)
    assert list(sizes.values()) == [2]


def test_cross_project_clustering_is_isolated(fresh_db):
    """Clustering must respect project isolation like everything else."""
    p1 = storage.create_project("P1", {})
    p2 = storage.create_project("P2", {})
    r1 = storage.start_run(p1, "news", {})
    r2 = storage.start_run(p2, "news", {})
    storage.save_items(p1, r1, "news", [_item("Maggi price rises in KL", "http://a", "2026-03-01")])
    storage.save_items(p2, r2, "news", [_item("Maggi price rises in KL", "http://a-p2", "2026-03-01")])
    # Each project's item is its own singleton cluster; no cross-project bleed.
    assert storage.count_unique_stories(p1) == 1
    assert storage.count_unique_stories(p2) == 1
