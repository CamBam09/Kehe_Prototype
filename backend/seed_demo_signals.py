"""
Seeds a few example TrendSignal rows directly into the database, so the
"Viral moment signals" card on the dashboard has something to show without
requiring a live call to Bluesky's public API.

This is here ONLY because this sandbox's network egress is restricted to
github.com/pypi.org/npmjs.org, so bluesky.py's real HTTP calls to
public.api.bsky.app return 403 here (confirmed with `curl -sI`) and the
scan-signals flow can't be exercised live in this environment. bluesky.py,
signals.py, and the /signals/scan endpoint are real, working code, verified
against mocked HTTP responses (see backend/tests/test_signals.py) - this
script does not change or bypass any of that logic, it just inserts rows a
successful scan would have inserted, so a person can see and use the
confirm/dismiss review UI today. Once this tool runs somewhere with normal
internet access, "Scan Bluesky for new signals" will populate this table
for real and this script becomes unnecessary.

Every row inserted here is clearly fictional: the keyword ties to a made-up
Bluesky spike and made-up sample posts, not anything that actually happened.

Usage:
    python3 seed_demo_signals.py
"""
import json
from datetime import date, datetime, timedelta

from app.database import SessionLocal, engine, Base
from app import models

Base.metadata.create_all(bind=engine)

TODAY = date(2026, 8, 31)  # matches the last date in the seeded demo sales history

SIGNALS = [
    {
        "keyword": "Snacks",
        "category": "Snacks",
        "window_start": TODAY - timedelta(days=2),
        "window_end": TODAY,
        "mention_count": 187,
        "baseline_mean": 22.4,
        "baseline_std": 6.1,
        "z_score": 4.7,
        "trends_corroborated": "yes",
        "sample_posts": [
            {
                "text": "FICTIONAL EXAMPLE POST - okay the kettle chip crunch videos are EVERYWHERE on my feed rn, "
                        "this brand specifically",
                "url": "https://bsky.app/profile/example.bsky.social/post/demo1",
                "author": "@example.bsky.social",
            },
            {
                "text": "FICTIONAL EXAMPLE POST - did the ASMR chip crunch trend just make sea salt kettle chips "
                        "cool again? asking for a friend",
                "url": "https://bsky.app/profile/example2.bsky.social/post/demo2",
                "author": "@example2.bsky.social",
            },
            {
                "text": "FICTIONAL EXAMPLE POST - three people sent me the same chip-crunch clip today, "
                        "the algorithm knows",
                "url": "https://bsky.app/profile/example3.bsky.social/post/demo3",
                "author": "@example3.bsky.social",
            },
        ],
        "status": "needs_review",
    },
    {
        "keyword": "Beverages",
        "category": "Beverages",
        "window_start": TODAY - timedelta(days=2),
        "window_end": TODAY,
        "mention_count": 61,
        "baseline_mean": 9.8,
        "baseline_std": 3.0,
        "z_score": 3.1,
        "trends_corroborated": "no",
        "sample_posts": [
            {
                "text": "FICTIONAL EXAMPLE POST - cold brew concentrate is the only thing getting me through "
                        "this week honestly",
                "url": "https://bsky.app/profile/example4.bsky.social/post/demo4",
                "author": "@example4.bsky.social",
            },
            {
                "text": "FICTIONAL EXAMPLE POST - saw an ad for this like four times today, so now I want it",
                "url": "https://bsky.app/profile/example5.bsky.social/post/demo5",
                "author": "@example5.bsky.social",
            },
        ],
        "status": "needs_review",
    },
    {
        "keyword": "Frozen",
        "category": "Frozen",
        "window_start": TODAY - timedelta(days=2),
        "window_end": TODAY,
        "mention_count": 44,
        "baseline_mean": 6.2,
        "baseline_std": 2.4,
        "z_score": 3.9,
        "trends_corroborated": "unavailable",
        "sample_posts": [
            {
                "text": "FICTIONAL EXAMPLE POST - frozen mango in the blender, no notes",
                "url": "https://bsky.app/profile/example6.bsky.social/post/demo6",
                "author": "@example6.bsky.social",
            },
        ],
        "status": "needs_review",
    },
]


def main():
    db = SessionLocal()
    try:
        existing = {(s.keyword, s.window_start) for s in db.query(models.TrendSignal).all()}
        created = 0
        for row in SIGNALS:
            key = (row["keyword"], row["window_start"])
            if key in existing:
                continue
            db.add(models.TrendSignal(
                keyword=row["keyword"],
                category=row["category"],
                window_start=row["window_start"],
                window_end=row["window_end"],
                mention_count=row["mention_count"],
                baseline_mean=row["baseline_mean"],
                baseline_std=row["baseline_std"],
                z_score=row["z_score"],
                trends_corroborated=row["trends_corroborated"],
                sample_posts=json.dumps(row["sample_posts"]),
                status=row["status"],
                created_at=datetime.utcnow(),
            ))
            created += 1
        db.commit()
        print(f"Inserted {created} demo trend signal(s) (skipped {len(SIGNALS) - created} already present).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
