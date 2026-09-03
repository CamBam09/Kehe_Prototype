"""
"What food & beverage topics are trending right now" via Google Trends
(pytrends), which is real public search-interest data, free, and needs no
API key or model. This replaced the original ask (scoring social media
comments/hashtags for "emotional momentum") because that needs paid
developer API access to platforms like X/Reddit/TikTok that this project
doesn't have, and because the repo originally suggested for it
(CamBam09/DeepSeek-V3) turned out to be an unmodified fork of a
671-billion-parameter general LLM with no such feature in it.

Important: pytrends calls trends.google.com directly, an ordinary HTTPS
request, not a model download. It could not be verified from the sandbox
this was built in, because that sandbox's network allowlist only permits
GitHub/PyPI/npm and blocks general web traffic (confirmed: trends.google.com,
google.com, and huggingface.co all return 403 from here, while
api.github.com and pypi/npm work fine). This is NOT a weights-download-style
obstacle: on a normal computer with ordinary internet access, this code
runs as-is. If it errors in a given environment (network policy, or
Google Trends' own rate limiting, which is real and can trigger on
repeated calls), get_foodbev_trends() returns available=False with a
`reason` string instead of raising, so the dashboard can show a clear
message rather than failing silently or fabricating a chart.
"""
import time
from typing import List, Dict, Optional
from collections import defaultdict

from sqlalchemy.orm import Session

from . import models

MAX_KEYWORDS_PER_REQUEST = 5  # Google Trends' own comparison limit
DEFAULT_TIMEFRAME = "today 12-m"
CACHE_TTL_SECONDS = 3600

FALLBACK_KEYWORDS = [
    "kombucha", "protein snacks", "oat milk", "mocktails", "kimchi",
]

_cache: Dict[str, tuple] = {}  # key -> (expires_at, TrendsResponse dict)


def default_keywords_from_catalog(db: Session, limit: int = 5) -> List[str]:
    """Pick the most common product categories in the loaded catalog so the
    trends chart reflects what's actually in KeHe's data rather than a
    generic hardcoded list. Falls back to a small curated list if the
    catalog is empty or has no categories yet."""
    rows = (
        db.query(models.Product.category)
        .filter(models.Product.category.isnot(None))
        .filter(models.Product.category != "Other")
        .all()
    )
    if not rows:
        return FALLBACK_KEYWORDS[:limit]

    counts: Dict[str, int] = defaultdict(int)
    for (category,) in rows:
        counts[category] += 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    keywords = [k for k, _ in ranked[:limit]]
    return keywords or FALLBACK_KEYWORDS[:limit]


def get_foodbev_trends(keywords: List[str], timeframe: str = DEFAULT_TIMEFRAME) -> dict:
    keywords = keywords[:MAX_KEYWORDS_PER_REQUEST]
    if not keywords:
        return {"available": False, "reason": "No keywords to search for.", "timeframe": timeframe, "series": []}

    cache_key = f"{'|'.join(sorted(keywords))}::{timeframe}"
    cached = _cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]

    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        pytrends.build_payload(keywords, cat=71, timeframe=timeframe, geo="US")  # cat 71 = Food & Drink
        df = pytrends.interest_over_time()

        if df is None or df.empty:
            result = {
                "available": False,
                "reason": "Google Trends returned no data for these keywords/timeframe.",
                "timeframe": timeframe,
                "series": [],
            }
        else:
            series = []
            for kw in keywords:
                if kw not in df.columns:
                    continue
                series.append({
                    "keyword": kw,
                    "dates": [d.date().isoformat() for d in df.index],
                    "interest": [int(v) for v in df[kw].tolist()],
                })
            result = {"available": True, "reason": None, "timeframe": timeframe, "series": series}

    except Exception as e:
        result = {
            "available": False,
            "reason": f"Could not reach Google Trends ({type(e).__name__}: {e}).",
            "timeframe": timeframe,
            "series": [],
        }

    _cache[cache_key] = (time.time() + CACHE_TTL_SECONDS, result)
    return result
