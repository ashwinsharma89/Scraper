"""Create a demo study through the wizard to prove the flow.

Uses an OBVIOUSLY FICTIONAL brand ("Acme Cola") in a real market ("Singapore"). This
exists only to demonstrate the intake -> config -> source-plan flow. It does NOT
fabricate any collected items or citations — honesty principle #2 (never simulate or
fabricate data) applies to the demo too. Run real collection to populate it.

Usage:  python seed_demo.py
Idempotent-ish: it will create a fresh "Acme Cola (demo)" project each time it runs.
"""
from __future__ import annotations

import config
import storage

DEMO_INTAKE = {
    "name": "Acme Cola (demo)",
    "market": {"country": "Singapore", "languages": ["en", "zh", "ms", "ta"]},
    "product": {
        "brand": "Acme Cola",
        "parent_company": "Acme Beverages (fictional)",
        "category": "carbonated soft drinks",
        "category_type": "fmcg_food",
    },
    # Fictional competitors — supplied by the (pretend) user, not hard-coded anywhere in the app.
    "competitors": ["Fizzly", "PopMax", "Zephyr Soda"],
    "keywords": {"trend_terms": ["sugar-free", "local flavor", "sustainability", "price hike"]},
}


def main() -> int:
    storage.init_db()
    cfg = config.run_wizard(DEMO_INTAKE)
    pid = storage.create_project(DEMO_INTAKE["name"], cfg)
    storage.audit("project.create", "demo seeded via wizard", acting_user="seed_demo",
                  project_id=pid)
    print(f"Created demo project #{pid}: {DEMO_INTAKE['name']}")
    print(f"  Market: {cfg['market']['country']} ({cfg['market']['country_code']}), "
          f"GDELT={cfg['market']['gdelt_country']}")
    print(f"  Languages: {', '.join(cfg['market']['languages'])}")
    print(f"  Google News feeds generated: {len(cfg['source_plan']['google_news_feeds'])}")
    print(f"  Subreddit candidates: {cfg['source_plan']['subreddits']}")
    print(f"  Delivery/quick-commerce segment: {cfg['source_plan']['segments']['delivery_quick_commerce']}")
    print("")
    print("Next: open the app, fill the empty source-plan slots (RSS/e-commerce/forum URLs) from")
    print("local knowledge, then run collection. No data is fabricated — the study starts empty.")
    return pid


if __name__ == "__main__":
    main()
