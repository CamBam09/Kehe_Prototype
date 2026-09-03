"""
Turns Bluesky mention counts into a reviewable "possible viral moment" flag.

This deliberately never writes to a product's viral_trend field on its own,
a mention spike can mean a recall, a controversy, or a coincidental keyword
match just as easily as a positive trend. run_scan() only creates
TrendSignal rows with status="needs_review"; a person reviews them (sample
posts included) and calls confirm_signal() or dismiss_signal() in main.py.
Only confirm_signal() ever touches viral_trend, and it appends rather than
overwrites, so it can never silently erase something a person entered by hand.
"""
import json
import statistics
from datetime import datetime, date as date_cls, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from . import models, bluesky, trends

Z_THRESHOLD = 2.5          # how many baseline std-devs above normal counts as a spike
MIN_RECENT_AVG = 5.0       # floor so a jump from 0 to 2 posts/day isn't flagged as "viral"
RECENT_WINDOW_DAYS = 3
DEDUPE_WINDOW_DAYS = 3     # don't re-flag the same keyword while a signal for it is still open


def _zscore_spike(counts: List[dict]) -> Optional[dict]:
    values = [c["count"] for c in counts]
    if len(values) < RECENT_WINDOW_DAYS + 5:
        return None
    baseline = values[:-RECENT_WINDOW_DAYS]
    recent = values[-RECENT_WINDOW_DAYS:]
    baseline_mean = statistics.mean(baseline)
    baseline_std = statistics.pstdev(baseline)
    recent_avg = statistics.mean(recent)
    denom = baseline_std if baseline_std > 0.5 else 0.5  # floor: avoid divide-by-near-zero blowups
    z = (recent_avg - baseline_mean) / denom
    return {
        "z_score": z,
        "baseline_mean": baseline_mean,
        "baseline_std": baseline_std,
        "recent_avg": recent_avg,
        "is_spike": z >= Z_THRESHOLD and recent_avg >= MIN_RECENT_AVG,
    }


def _check_trends_corroboration(keyword: str) -> str:
    """"yes" / "no" / "unavailable". A spike is more trustworthy when Google
    Trends search interest for the same keyword is also elevated right now."""
    result = trends.get_foodbev_trends([keyword])
    if not result.get("available") or not result.get("series"):
        return "unavailable"
    series = result["series"][0]["interest"]
    if len(series) < 6:
        return "unavailable"
    recent_avg = statistics.mean(series[-2:])
    baseline_mean = statistics.mean(series[:-2])
    return "yes" if (recent_avg > baseline_mean * 1.3 and recent_avg > 5) else "no"


def run_scan(db: Session, keywords: List[str]) -> dict:
    created = 0
    checked = []
    last_error = None

    for keyword in keywords:
        recent_cutoff = datetime.utcnow() - timedelta(days=DEDUPE_WINDOW_DAYS)
        already_open = (
            db.query(models.TrendSignal)
            .filter(models.TrendSignal.keyword == keyword)
            .filter(models.TrendSignal.status == "needs_review")
            .filter(models.TrendSignal.created_at >= recent_cutoff)
            .first()
        )
        if already_open:
            checked.append(keyword)
            continue

        try:
            counts = bluesky.daily_mention_counts(keyword)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
        checked.append(keyword)

        spike = _zscore_spike(counts)
        if not spike or not spike["is_spike"]:
            continue

        window_end = date_cls.fromisoformat(counts[-1]["date"])
        window_start = date_cls.fromisoformat(counts[-RECENT_WINDOW_DAYS]["date"])
        try:
            posts = bluesky.sample_posts(keyword, window_start, window_end, n=3)
        except Exception:
            posts = []
        corroborated = _check_trends_corroboration(keyword)

        db.add(models.TrendSignal(
            keyword=keyword,
            category=keyword,  # keywords are drawn straight from Product.category, see trends.py
            window_start=window_start,
            window_end=window_end,
            mention_count=sum(c["count"] for c in counts[-RECENT_WINDOW_DAYS:]),
            baseline_mean=spike["baseline_mean"],
            baseline_std=spike["baseline_std"],
            z_score=spike["z_score"],
            trends_corroborated=corroborated,
            sample_posts=json.dumps(posts),
            status="needs_review",
        ))
        created += 1

    db.commit()

    reason = None
    if not checked and last_error:
        reason = f"Could not reach Bluesky ({last_error})."
    return {"keywords_checked": checked, "signals_created": created, "reason": reason}


def confirm_signal(db: Session, signal_id: int, product_id: int, note: Optional[str]) -> models.TrendSignal:
    signal = db.query(models.TrendSignal).filter(models.TrendSignal.id == signal_id).first()
    if not signal:
        raise ValueError("Signal not found")
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise ValueError("Product not found")

    today = datetime.utcnow().date().isoformat()
    entry = (
        f"[Detected & confirmed {today}] Bluesky mention spike for '{signal.keyword}': "
        f"~{signal.mention_count} posts over {RECENT_WINDOW_DAYS} days vs a baseline of "
        f"~{signal.baseline_mean:.1f}/day (z={signal.z_score:.1f}"
        f"{', Google Trends corroborated' if signal.trends_corroborated == 'yes' else ''})."
    )
    if note:
        entry += f" Note: {note}"

    product.viral_trend = f"{product.viral_trend}\n{entry}" if product.viral_trend else entry
    signal.status = "confirmed"
    signal.confirmed_product_id = product_id
    signal.note = note
    signal.resolved_at = datetime.utcnow()
    db.commit()
    return signal


def dismiss_signal(db: Session, signal_id: int, note: Optional[str]) -> models.TrendSignal:
    signal = db.query(models.TrendSignal).filter(models.TrendSignal.id == signal_id).first()
    if not signal:
        raise ValueError("Signal not found")
    signal.status = "dismissed"
    signal.note = note
    signal.resolved_at = datetime.utcnow()
    db.commit()
    return signal
