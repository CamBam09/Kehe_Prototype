# KeHe Trend Tool (prototype)

A working prototype for uploading a product catalog, searching it, and tracking/
predicting sales trends by product and region, with a dashboard homepage showing
current food & beverage trend data alongside the catalog's sales overview. Built
to be run and extended, not a finished production system, see "What's real vs.
what's a placeholder" below.

## What it does right now

- Upload a product catalog (CSV) and a sales history (CSV) into a real database.
- Search the catalog by name, SKU, brand, or category.
- Generate a forecast for future sales, per product and per region, using
  Nixtla's AutoARIMA (trained on that product's own history, no pretrained
  weights needed).
- Detect which calendar month each product/region peaks and troughs in.
- A dashboard homepage (`frontend/index.html`) showing: a live Google Trends
  line chart of what's trending in food & beverage right now, built from
  keywords pulled from your own catalog's categories; and a baseline-vs-forecast
  sales chart for whichever products actually have sales data loaded.
- View a chart of historical + forecasted units for any product on the catalog
  page (`frontend/catalog.html`).
- 70 real KeHE products pre-built and ready to load (`backend/data/kehe_products.csv`),
  sourced from KeHE's public retailers/brand-partner page, see the honesty note
  below on what this data does and doesn't include.
- A "viral trend" field per product: a free-text note for documenting a known
  viral social media moment that affected a product's sales (platform, date,
  what happened). This is filled in by hand, by whoever uploads the catalog,
  not detected automatically, there's no live social-listening in this tool
  (see the DeepSeek-V3 note below for why). Shows as its own column in the
  catalog table, next to Baseline sales, and as a callout on the product detail
  page when one is documented; the detail page's original 5 stat boxes
  (brand/category/baseline sales/source/product link) are unchanged.
- Dashboard and Catalog are now proper clickable tabs in the header, shared
  across both pages, rather than a single "back" link.
- **Real-time viral-moment detection.** A "Viral moment signals" card on the
  dashboard scans Bluesky's public API for a mention-count spike in each
  catalog category, checks it against a z-score of that keyword's own recent
  baseline, cross-checks it against Google Trends, and lists anything that
  spikes as a reviewable flag with sample posts. It never writes to a
  product's "Viral trend" field on its own — a person confirms (which appends
  to that field, never overwriting an existing note) or dismisses each flag.
  See "Viral-moment detection" below for the full design.

Tested end to end before delivery: catalog upload (both the synthetic demo data
and the real 70-product KeHE set), sales upload, search, forecasting (which
correctly skips products with no sales history rather than fabricating a
forecast for them), and seasonality detection all ran successfully against a
live local server, as did the full signal review workflow (scan → confirm →
product note updated / dismiss → note discarded), using seeded example signals
in place of a live Bluesky scan (see below for why). The Google Trends piece
was written and unit-tested against a mocked response for the same reason.
The spike-detection logic itself (z-score math, dedupe, confirm/dismiss) has
11 automated tests in `backend/tests/test_signals.py`, all passing.

## Running it

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open `frontend/index.html` for the dashboard, or `frontend/catalog.html`
to search/upload (they link to each other). Both talk to the API at
`http://localhost:8000`. No build step, no separate frontend server.

The database defaults to a local SQLite file at `backend/data/kehe_trends.db`,
created automatically on first run. For real use, point it at Postgres instead:

```bash
export DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/kehe_trends"
```

(`pip install psycopg2-binary` first if you go this route.) Postgres is the
recommended target long-term, both for concurrent access and because it can
grow into `pgvector` for the semantic search upgrade described below.

## Trying it with example data

Two separate datasets, kept deliberately separate and tagged by `data_source`
so the dashboard is always honest about which is which:

**Synthetic demo data** (`backend/seed_demo_data.py`): a SYNTHETIC catalog of
10 fictional food & beverage products with three years of fabricated monthly
sales history and made-up seasonal patterns baked in, purely so you can see
search, forecasting, and the sales chart work end to end. None of it is real.

**Real KeHE catalog data** (`backend/data/kehe_products.csv`, already built):
70 real products from 10 brands KeHE spotlights on its public retailers page
(CADIA, MADE•WITH, Di Martino Pasta, and others), with real names, brands, and
links back to each product. This has NO sales figures, on purpose, see the
honesty note below.

```bash
cd backend
python3 seed_demo_data.py     # (re)writes data/catalog_demo.csv and data/sales_demo.csv
uvicorn app.main:app --reload --port 8000   # in one terminal
# in another terminal:
curl -F "file=@data/catalog_demo.csv"   http://localhost:8000/ingest/catalog
curl -F "file=@data/sales_demo.csv"     http://localhost:8000/ingest/sales
curl -F "file=@data/kehe_products.csv"  http://localhost:8000/ingest/catalog
curl -X POST "http://localhost:8000/forecast/all"
python3 seed_demo_signals.py   # optional: seeds example viral-moment signals to review, see below
```

Then open `frontend/index.html` for the dashboard (trend chart + sales overview),
or `frontend/catalog.html`, search for something like "soup" or "pasta", and
click a result to see its detail page.

## Loading real KeHe sales data

Catalog CSV (`/ingest/catalog`), only `sku` and `name` are required, everything
else is optional: `sku, name, brand, category, description, baseline_sales,
primary_region, viral_trend, source_url, data_source`. Upserts by `sku`, so
re-uploading updates existing products rather than duplicating them. Leaving
`baseline_sales` blank is different from setting it to 0: blank means "no data
yet" and the dashboard/catalog page both show that honestly instead of treating
it as zero sales. `viral_trend` is free text, e.g. `"TikTok - Nov 2025:
cranberry sauce recipe videos, baseline roughly doubled for 3 weeks"`, leave it
blank unless a real viral moment for that product is actually known.

Sales history CSV (`/ingest/sales`): `sku, region, period_date, units_sold`.
`period_date` accepts `YYYY-MM-DD` or `YYYY-MM` (monthly). The catalog must be
loaded first, since sales rows are matched to products by `sku`.

If the catalog only exists as PDFs, scans, or photographed sheets rather than
a spreadsheet or system export, see the Docling note below before trying to
force it through the CSV path.

## Viral-moment detection (Bluesky + spike detection + Google Trends)

This replaces manual-only entry in the "Viral trend" field with a real,
working detection pipeline. It never overrides a person: automated detection
only ever produces a flag someone reviews.

**Why Bluesky.** Of the major social platforms, Bluesky is the only one with
a public, free, real-time search API with no commercial-use restriction: X
has no free tier for search as of this build, Reddit's free tier is
non-commercial-only (its commercial API is a paid enterprise product), and
TikTok/Meta's research APIs explicitly exclude commercial entities like KeHe.
Bluesky's `app.bsky.feed.searchPosts` endpoint is public, unauthenticated, and
usable by a commercial project today. It's one data source, not a full
picture of "what's viral" everywhere, but it's the one genuinely open option
(see `backend/app/bluesky.py` for the full rationale in code).

**How a signal gets created** (`backend/app/signals.py`):
1. For each catalog category (or explicit keyword), `bluesky.py` fetches the
   daily mention count for the last 21 days from Bluesky's public search API.
2. `_zscore_spike()` compares the last 3 days' average against the mean/stdev
   of the 18 days before that. A spike is flagged only if the z-score clears
   2.5 **and** the recent volume clears a minimum floor (5/day), so a jump
   from 0 to 2 mentions isn't mistaken for a real trend.
3. If it's a spike, up to 3 sample posts are pulled for a human to sanity-check,
   and the same keyword is checked against Google Trends search interest as a
   second, independent signal (`trends_corroborated`: yes/no/unavailable).
4. A `TrendSignal` row is created with `status="needs_review"`. A keyword with
   an already-open signal isn't re-flagged for 3 days (dedupe).

**Human review, always.** The dashboard's "Viral moment signals" card lists
every `needs_review` signal with its stats, sample posts, and a dropdown of
catalog products in that category. A person either:
- **Confirms** it against a specific product — this *appends* a note like
  `[Detected & confirmed 2026-09-02] Bluesky mention spike for 'Snacks': ...`
  to that product's `viral_trend` field, never overwriting whatever was there
  before (hand-entered notes are always preserved), or
- **Dismisses** it as noise/a false positive, which just records the decision.

`POST /signals/scan` runs a scan on demand, `GET /signals` lists signals by
status, `POST /signals/{id}/confirm` and `POST /signals/{id}/dismiss` record
the review decision.

**Trying it without live Bluesky access:** the sandbox this was built in can't
reach `public.api.bsky.app` (see the honesty note below), so
`backend/seed_demo_signals.py` inserts a few clearly-labeled fictional example
signals directly into the database — enough to exercise the review UI without
a live scan:

```bash
cd backend
python3 seed_demo_signals.py
```

Then open the dashboard and use the "Viral moment signals" card as normal.
Once this runs somewhere with normal internet access, "Scan Bluesky for new
signals" populates this table for real and the seed script becomes unnecessary.

## What's real vs. what's a placeholder

This was built and tested inside a sandboxed cloud environment whose network
access is limited to an allowlist (GitHub, PyPI, and npm; general web traffic,
including Hugging Face and Google, is blocked from that sandbox specifically).
A few pieces of the architecture are wired in as documented drop-in points
rather than exercised live there, for two different reasons:

- **Semantic catalog search** (`backend/app/search.py`). Works today via BM25
  keyword matching, which finds products by name/SKU/category/brand terms
  correctly but won't catch synonyms or paraphrased queries. The file documents
  the exact swap to BGE-M3 embeddings + LlamaIndex; it needs `BAAI/bge-m3`'s
  weights from Hugging Face.
- **PDF/scanned catalog parsing** (`backend/app/ingestion.py`,
  `ingest_catalog_document`, `/ingest/catalog-document`). Raises a clear error
  explaining why, with the exact Docling + Granite-Docling-258M code to drop in
  once you run this somewhere that can reach Hugging Face, or with that model's
  weights downloaded locally.
- **The trends dashboard** (`backend/app/trends.py`, `/trends/foodbev`). This
  is different from the two above: it doesn't need any model weights, it's an
  ordinary HTTPS call to Google Trends via the `pytrends` library. It simply
  could not be reached from this specific build sandbox (`trends.google.com`
  returns 403 there, same as `google.com` generally). On your own computer,
  with normal internet access, this should just work as written; I verified
  its data-handling logic against a mocked Google Trends response rather than
  a live one. If it errors for you too, `/trends/foodbev` returns
  `{"available": false, "reason": "..."}` with the actual error rather than
  crashing, so the dashboard will show you why instead of failing silently.
- **Viral-moment detection's Bluesky calls** (`backend/app/bluesky.py`). Same
  situation as Google Trends: an ordinary HTTPS call, this time to
  `public.api.bsky.app`, blocked by this same sandbox allowlist (confirmed
  with `curl -sI`, also a 403). The spike-detection math, dedupe logic, and
  the confirm/dismiss workflow are all real and fully verified (11 passing
  tests in `backend/tests/test_signals.py`, using mocked mention-count data);
  only the live HTTP call to Bluesky itself couldn't be exercised here. The
  dashboard's demo data was seeded via `backend/seed_demo_signals.py` for
  that reason, clearly labeled as fictional example signals, not real
  detected activity. `/signals/scan` returns a `reason` explaining the
  network failure rather than crashing if Bluesky is unreachable for you too.

Forecasting (Nixtla/AutoARIMA), the database, ingestion, search, and the
signals review workflow (confirm/dismiss/dedupe, once a signal exists) all
needed no pretrained weights or blocked network calls, so those pieces are
real and were verified working end to end against both the synthetic demo
data and the real 70-product KeHE set, not just written and left untested.

**On the original "emotional momentum from social media" idea:** the repo
initially suggested for this (`CamBam09/DeepSeek-V3`) turned out to be an
unmodified fork of the official DeepSeek-V3 model, a general-purpose 671-billion-
parameter LLM with no code in it for analyzing comments, hashtags, or public
feeds, and not something realistically self-hostable for this project regardless.
The real-time detection now in this tool (Bluesky mention spikes + Google
Trends corroboration, described above) is what replaced that idea after
researching current platform API access: no paid developer keys required,
no massive model, and unlike the DeepSeek-V3 fork it's a working pipeline
you can actually run.

**On the KeHE product data:** the 70 products in `kehe_products.csv` are real
products, brands, and links, sourced from KeHE's public retailers/brand-partner
marketing page (`kehe.com/retailers`) and each brand's own storefront, per the
Google Sheet used to build this list. They are NOT KeHE's internal ~8,500-brand
catalog, which lives behind KeHE's login-gated CONNECT Retailer portal, and they
carry no baseline sales, sales history, or region data, because none was ever
available for them. Every row is tagged `data_source=kehe_public_marketing_page`
so the app never presents them as having sales data they don't have. To get real
baseline/forecast charts for these (or any) products, load an actual sales
export through `/ingest/sales`.

## Project layout

```
backend/
  app/
    main.py              - FastAPI routes
    models.py             - database schema (products, sales_records, forecasts, trend_signals)
    schemas.py             - API request/response shapes
    database.py             - SQLite by default, swap to Postgres via DATABASE_URL
    ingestion.py             - CSV catalog/sales loading + the Docling hook
    search.py                 - BM25 search + the BGE-M3/LlamaIndex upgrade path
    forecasting.py             - AutoARIMA forecasting + seasonality detection
    trends.py                   - Google Trends (pytrends) integration for the dashboard
    bluesky.py                   - Bluesky public-API mention counting for signals
    signals.py                    - spike detection + Trends corroboration + confirm/dismiss
  tests/
    test_signals.py      - 11 tests for spike detection, dedupe, confirm/dismiss (mocked data)
  seed_demo_data.py       - generates the synthetic example catalog/sales data described above
  seed_demo_signals.py    - inserts a few fictional example TrendSignal rows (see above)
  build_kehe_catalog.py   - (re)generates data/kehe_products.csv from the real KeHE brand/product list
  requirements.txt
frontend/
  index.html         - dashboard homepage: trends chart, viral-signal review card, sales overview
  catalog.html        - search, catalog/sales upload, per-product detail + chart
```
