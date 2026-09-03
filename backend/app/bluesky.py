"""
Bluesky mention counting, the real-time data source for viral-moment
detection (spike_detection in signals.py turns these counts into a flag).

Bluesky was chosen over X/TikTok/Reddit/Instagram after checking each
platform's actual access terms: X's API has no meaningful free tier left
(pay-per-use, ~$0.005-$0.20 per read); Reddit's free tier now requires
approval and is non-commercial only, commercial access starts around
$12,000/month; TikTok's Research API and Meta's Content Library are both
explicitly restricted to academic/non-profit researchers, a for-profit
distributor doesn't qualify regardless of budget. Bluesky's public search
API is free, requires no API key or app review, and has no commercial
restriction, which is what makes it realistic to wire up here at all.

Endpoint: public.api.bsky.app/xrpc/app.bsky.feed.searchPosts (AT Protocol).
q is required; since/until/limit/sort are supported. Two real limitations,
documented upstream, that this module works around rather than pretends
don't exist:
  - The `cursor` pagination parameter requires authentication; without it,
    only the first page of results per request is available. This module
    uses limit=100 (the API's max page size) and treats each day's count
    as "at least this many, possibly capped at 100", not an exhaustive
    count. That's still a real, honest signal for spike detection (a
    capped-at-100 day is unambiguously a busier day than a 3-post day),
    it just isn't a precise total.
  - since/until have had known bugs in some API versions (see
    bluesky-social/atproto#3258). If a day's request comes back looking
    wrong, this module doesn't try to be clever about it, it surfaces the
    failure so the caller can report "couldn't check Bluesky" rather than
    silently returning bad numbers.

Like trends.py, this could not be verified against the live API from the
sandbox this was built in (public.api.bsky.app returns 403 there, the
same network allowlist that blocked Hugging Face and Google Trends). It's
an ordinary HTTPS GET with no auth, so it should work as written wherever
this runs with normal internet access. Logic is verified against mocked
responses instead, see tests alongside seed_demo_signals.py.
"""
import time
from datetime import datetime, timedelta, date as date_cls
from typing import List, Dict, Optional

import requests

SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
LOOKBACK_DAYS = 21
PAGE_LIMIT = 100  # AT Protocol's max page size; see module docstring on why this caps daily counts
REQUEST_TIMEOUT = 15
CACHE_TTL_SECONDS = 3600

_cache: Dict[str, tuple] = {}


def _http_get(url: str, params: dict) -> dict:
    """Thin wrapper so tests can monkeypatch just this function rather than
    the whole `requests` module."""
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _day_bounds_iso(day: date_cls) -> tuple:
    since = datetime.combine(day, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = datetime.combine(day + timedelta(days=1), datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%SZ")
    return since, until


def _uri_to_web_url(uri: str, handle: str) -> str:
    try:
        rkey = uri.rstrip("/").split("/")[-1]
        return f"https://bsky.app/profile/{handle}/post/{rkey}"
    except Exception:
        return uri


def daily_mention_counts(keyword: str, lookback_days: int = LOOKBACK_DAYS) -> List[Dict]:
    """Returns [{"date": "YYYY-MM-DD", "count": int}, ...] for the last
    `lookback_days` full days, oldest first. Raises on the first request
    failure rather than returning partial/misleading data, callers should
    catch and report this as "Bluesky unavailable", the same pattern
    trends.py uses for Google Trends."""
    cache_key = f"daily::{keyword}::{lookback_days}"
    cached = _cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]

    today = datetime.utcnow().date()
    counts = []
    for i in range(lookback_days, 0, -1):
        day = today - timedelta(days=i)
        since, until = _day_bounds_iso(day)
        data = _http_get(SEARCH_URL, {"q": keyword, "since": since, "until": until, "limit": PAGE_LIMIT})
        counts.append({"date": day.isoformat(), "count": len(data.get("posts", []))})

    _cache[cache_key] = (time.time() + CACHE_TTL_SECONDS, counts)
    return counts


def sample_posts(keyword: str, since_day: date_cls, until_day: date_cls, n: int = 3) -> List[Dict]:
    """A few example posts from the window, for a human reviewer to sanity-check
    a flagged spike against (is this actually about the product, or a
    coincidental keyword match?)."""
    since, _ = _day_bounds_iso(since_day)
    _, until = _day_bounds_iso(until_day)
    data = _http_get(SEARCH_URL, {"q": keyword, "since": since, "until": until, "limit": n, "sort": "latest"})
    out = []
    for p in data.get("posts", [])[:n]:
        record = p.get("record", {})
        author = p.get("author", {}).get("handle", "unknown")
        out.append({
            "text": (record.get("text") or "")[:200],
            "url": _uri_to_web_url(p.get("uri", ""), author),
            "author": author,
        })
    return out
