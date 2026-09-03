"""
Tests for the Bluesky spike-detection pipeline (bluesky.py + signals.py).

These run against mocked HTTP responses rather than live calls, because this
sandbox's network egress is restricted to github.com/pypi.org/npmjs.org and
public.api.bsky.app / trends.google.com both return 403 here (verified with
`curl -sI`). The logic under test - z-score spike detection, dedupe, and the
confirm/dismiss human-in-the-loop flow - does not depend on live network
access to be correct, so it's fully verified here; only the actual HTTP call
in bluesky._http_get is faked. Run with:

    cd backend
    pip install pytest --break-system-packages
    python3 -m pytest tests/ -v
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models, signals, bluesky, trends


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _flat_counts(n=24, value=8):
    today = date(2026, 8, 31)
    return [{"date": (today - timedelta(days=n - 1 - i)).isoformat(), "count": value} for i in range(n)]


def _spiking_counts(n=24, baseline=6, spike=60):
    counts = _flat_counts(n, baseline)
    for row in counts[-3:]:
        row["count"] = spike
    return counts


# ---- _zscore_spike -----------------------------------------------------

def test_zscore_spike_detects_real_spike():
    result = signals._zscore_spike(_spiking_counts())
    assert result is not None
    assert result["is_spike"] is True
    assert result["z_score"] >= signals.Z_THRESHOLD


def test_zscore_spike_flat_history_is_not_a_spike():
    result = signals._zscore_spike(_flat_counts())
    assert result is not None
    assert result["is_spike"] is False


def test_zscore_spike_too_little_history_returns_none():
    result = signals._zscore_spike(_flat_counts(n=5))
    assert result is None


def test_zscore_spike_low_absolute_volume_not_flagged():
    # z-score can look large on tiny numbers (0 -> 2 mentions/day); MIN_RECENT_AVG
    # exists specifically so that isn't flagged as "viral".
    counts = _flat_counts(n=24, value=0)
    for row in counts[-3:]:
        row["count"] = 2
    result = signals._zscore_spike(counts)
    assert result["is_spike"] is False


# ---- run_scan ------------------------------------------------------------

def test_run_scan_only_flags_the_spiking_keyword(db, monkeypatch):
    def fake_daily_counts(keyword, lookback_days=21):
        if keyword == "Snacks":
            return _spiking_counts()
        return _flat_counts()

    monkeypatch.setattr(bluesky, "daily_mention_counts", fake_daily_counts)
    monkeypatch.setattr(bluesky, "sample_posts", lambda *a, **k: [])
    monkeypatch.setattr(trends, "get_foodbev_trends", lambda kws, timeframe="today 12-m": {"available": False, "series": []})

    result = signals.run_scan(db, ["Snacks", "Soups"])

    assert result["keywords_checked"] == ["Snacks", "Soups"]
    assert result["signals_created"] == 1
    rows = db.query(models.TrendSignal).all()
    assert len(rows) == 1
    assert rows[0].keyword == "Snacks"
    assert rows[0].status == "needs_review"
    assert rows[0].trends_corroborated == "unavailable"


def test_run_scan_dedupes_before_any_review(db, monkeypatch):
    monkeypatch.setattr(bluesky, "daily_mention_counts", lambda keyword, lookback_days=21: _spiking_counts())
    monkeypatch.setattr(bluesky, "sample_posts", lambda *a, **k: [])
    monkeypatch.setattr(trends, "get_foodbev_trends", lambda kws, timeframe="today 12-m": {"available": False, "series": []})

    signals.run_scan(db, ["Snacks"])
    signals.run_scan(db, ["Snacks"])  # same keyword, still needs_review -> should not duplicate

    open_signals = db.query(models.TrendSignal).filter(models.TrendSignal.status == "needs_review").all()
    assert len(open_signals) == 1


def test_run_scan_reports_reason_when_nothing_reachable(db, monkeypatch):
    def always_fails(keyword, lookback_days=21):
        raise ConnectionError("403 Forbidden")

    monkeypatch.setattr(bluesky, "daily_mention_counts", always_fails)

    result = signals.run_scan(db, ["Snacks", "Soups"])

    assert result["signals_created"] == 0
    assert result["keywords_checked"] == []
    assert "403" in result["reason"]


# ---- confirm_signal / dismiss_signal --------------------------------------

def _make_signal(db, keyword="Snacks", category="Snacks"):
    s = models.TrendSignal(
        keyword=keyword,
        category=category,
        window_start=date(2026, 8, 29),
        window_end=date(2026, 8, 31),
        mention_count=120,
        baseline_mean=10.0,
        baseline_std=3.0,
        z_score=5.2,
        trends_corroborated="yes",
        sample_posts="[]",
        status="needs_review",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_confirm_signal_appends_to_empty_viral_trend(db):
    product = models.Product(sku="DEMO-1", name="Test Chips", category="Snacks")
    db.add(product)
    db.commit()
    db.refresh(product)
    sig = _make_signal(db)

    updated = signals.confirm_signal(db, sig.id, product.id, note="Looks legit")

    assert updated.status == "confirmed"
    assert updated.confirmed_product_id == product.id
    db.refresh(product)
    assert "Snacks" in product.viral_trend
    assert "Looks legit" in product.viral_trend


def test_confirm_signal_appends_without_erasing_existing_text(db):
    product = models.Product(
        sku="DEMO-2", name="Test Muffin Mix", category="Bakery",
        viral_trend="Hand-entered note from last quarter, do not lose this.",
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    sig = _make_signal(db, keyword="Bakery", category="Bakery")

    signals.confirm_signal(db, sig.id, product.id, note=None)

    db.refresh(product)
    assert "Hand-entered note from last quarter, do not lose this." in product.viral_trend
    assert "Bakery" in product.viral_trend


def test_dismiss_signal_marks_dismissed_and_leaves_products_alone(db):
    product = models.Product(sku="DEMO-3", name="Test Soup", category="Soups")
    db.add(product)
    db.commit()
    sig = _make_signal(db, keyword="Soups", category="Soups")

    updated = signals.dismiss_signal(db, sig.id, note="Just a promo, not organic")

    assert updated.status == "dismissed"
    assert updated.note == "Just a promo, not organic"
    db.refresh(product)
    assert product.viral_trend is None


def test_confirm_signal_unknown_id_raises(db):
    with pytest.raises(ValueError):
        signals.confirm_signal(db, 9999, 1, None)
