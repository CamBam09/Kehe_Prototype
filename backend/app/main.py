"""
KeHe Trend Tool - API

Run with:
    cd backend
    uvicorn app.main:app --reload --port 8000

Then open frontend/index.html (it calls this API at http://localhost:8000).
"""
import json
import os
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models, ingestion, search, forecasting, trends, signals
from .database import engine, get_db, Base
from .schemas import (
    ProductOut, ProductDetail, SalesPoint, ForecastPoint, SeasonalInsight,
    IngestSummary, SearchResult, TrendsResponse, DashboardSummary,
    TrendSignalOut, ScanSummary, ConfirmSignalRequest,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="KeHe Trend Tool", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest/catalog", response_model=IngestSummary)
def ingest_catalog(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a product catalog CSV: sku, name, category, description, baseline_sales, primary_region"""
    try:
        count, warnings = ingestion.ingest_catalog_csv(db, file.file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return IngestSummary(products_loaded=count, sales_records_loaded=0, warnings=warnings)


@app.post("/ingest/sales", response_model=IngestSummary)
def ingest_sales(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload historical sales CSV: sku, region, period_date, units_sold"""
    try:
        count, warnings = ingestion.ingest_sales_csv(db, file.file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return IngestSummary(products_loaded=0, sales_records_loaded=count, warnings=warnings)


@app.post("/ingest/catalog-document")
def ingest_catalog_document(file: UploadFile = File(...)):
    """PDF/scanned catalog ingestion via Docling + Granite-Docling-258M. See ingestion.py."""
    try:
        ingestion.ingest_catalog_document(file.file.read(), file.filename)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@app.get("/products", response_model=List[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(models.Product).order_by(models.Product.name).all()


@app.get("/search", response_model=List[SearchResult])
def search_catalog(q: str = Query(..., min_length=1), top_k: int = 10, db: Session = Depends(get_db)):
    results = search.search(db, q, top_k=top_k)
    return [SearchResult(product=p, score=round(float(s), 3)) for p, s in results]


@app.get("/products/{product_id}", response_model=ProductDetail)
def product_detail(product_id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    history = (
        db.query(models.SalesRecord)
        .filter(models.SalesRecord.product_id == product_id)
        .order_by(models.SalesRecord.period_date)
        .all()
    )
    forecast_rows = (
        db.query(models.Forecast)
        .filter(models.Forecast.product_id == product_id)
        .order_by(models.Forecast.period_date)
        .all()
    )
    seasonality = forecasting.compute_seasonality(db, product_id)

    return ProductDetail(
        product=product,
        history=[SalesPoint.model_validate(h) for h in history],
        forecast=[ForecastPoint.model_validate(f) for f in forecast_rows],
        seasonality=seasonality,
    )


@app.post("/products/{product_id}/forecast", response_model=List[ForecastPoint])
def run_forecast(product_id: int, periods: int = 6, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    created = forecasting.generate_forecast(db, product_id, periods=periods)
    return [ForecastPoint.model_validate(f) for f in created]


@app.post("/forecast/all")
def run_forecast_all(periods: int = 6, db: Session = Depends(get_db)):
    """Convenience endpoint: (re)generate forecasts for every product with sales history.
    Products with no sales_records yet (e.g. catalog-only entries) are skipped, not
    given a fabricated forecast."""
    product_ids = [p.id for p in db.query(models.Product.id).all()]
    total = 0
    forecasted = 0
    for pid in product_ids:
        created = forecasting.generate_forecast(db, pid, periods=periods)
        if created:
            forecasted += 1
        total += len(created)
    return {"products_forecasted": forecasted, "forecast_rows_written": total}


@app.get("/trends/foodbev", response_model=TrendsResponse)
def foodbev_trends(
    keywords: str = Query("", description="Comma-separated search terms; defaults to top categories in the catalog"),
    timeframe: str = Query("today 12-m"),
    db: Session = Depends(get_db),
):
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or trends.default_keywords_from_catalog(db)
    result = trends.get_foodbev_trends(kw_list, timeframe=timeframe)
    return result


def _signal_to_out(db: Session, s: models.TrendSignal) -> TrendSignalOut:
    try:
        sample_posts = json.loads(s.sample_posts) if s.sample_posts else []
    except (TypeError, ValueError):
        sample_posts = []
    matching = []
    if s.category:
        matching = (
            db.query(models.Product)
            .filter(models.Product.category == s.category)
            .order_by(models.Product.name)
            .limit(20)
            .all()
        )
    # Built from a plain dict rather than TrendSignalOut.model_validate(s): the ORM
    # object's sample_posts column is a raw JSON string, which fails validation
    # against the List[SamplePost] field before we get a chance to replace it.
    return TrendSignalOut.model_validate({
        "id": s.id,
        "keyword": s.keyword,
        "category": s.category,
        "window_start": s.window_start,
        "window_end": s.window_end,
        "mention_count": s.mention_count,
        "baseline_mean": s.baseline_mean,
        "baseline_std": s.baseline_std,
        "z_score": s.z_score,
        "trends_corroborated": s.trends_corroborated,
        "sample_posts": sample_posts,
        "status": s.status,
        "confirmed_product_id": s.confirmed_product_id,
        "note": s.note,
        "created_at": s.created_at,
        "matching_products": matching,
    })


@app.post("/signals/scan", response_model=ScanSummary)
def scan_signals(
    keywords: str = Query("", description="Comma-separated keywords; defaults to top categories in the catalog"),
    db: Session = Depends(get_db),
):
    """Checks Bluesky mention volume for each keyword against its own recent
    baseline; anything spiking becomes a needs_review TrendSignal. Never
    writes to a product directly, see signals.py."""
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or trends.default_keywords_from_catalog(db)
    result = signals.run_scan(db, kw_list)
    return ScanSummary(
        keywords_checked=result["keywords_checked"],
        signals_created=result["signals_created"],
        reason=result["reason"],
    )


@app.get("/signals", response_model=List[TrendSignalOut])
def list_signals(status: str = Query("needs_review"), db: Session = Depends(get_db)):
    q = db.query(models.TrendSignal)
    if status != "all":
        q = q.filter(models.TrendSignal.status == status)
    rows = q.order_by(models.TrendSignal.created_at.desc()).all()
    return [_signal_to_out(db, s) for s in rows]


@app.post("/signals/{signal_id}/confirm", response_model=TrendSignalOut)
def confirm_signal(signal_id: int, body: ConfirmSignalRequest, db: Session = Depends(get_db)):
    try:
        s = signals.confirm_signal(db, signal_id, body.product_id, body.note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _signal_to_out(db, s)


@app.post("/signals/{signal_id}/dismiss", response_model=TrendSignalOut)
def dismiss_signal(signal_id: int, note: str = Query(None), db: Session = Depends(get_db)):
    try:
        s = signals.dismiss_signal(db, signal_id, note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _signal_to_out(db, s)


@app.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)):
    all_products = db.query(models.Product).all()
    with_sales = [p for p in all_products if p.baseline_sales is not None]
    without_sales = [p for p in all_products if p.baseline_sales is None]
    top = sorted(with_sales, key=lambda p: p.baseline_sales, reverse=True)[:8]
    pending = db.query(models.TrendSignal).filter(models.TrendSignal.status == "needs_review").count()
    return DashboardSummary(
        total_products=len(all_products),
        products_with_sales_data=len(with_sales),
        products_without_sales_data=len(without_sales),
        top_products_by_baseline=top,
        pending_signals=pending,
    )


# Serves frontend/index.html, catalog.html, etc. at the same origin as the API,
# so the deployed app is a single service with no CORS/API_BASE juggling.
# Mounted last so it only catches paths that don't match a route above.
_frontend_dir = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parent.parent.parent / "frontend"))
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
