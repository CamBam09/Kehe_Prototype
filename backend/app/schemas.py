"""Pydantic request/response models for the API."""
from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = ""
    baseline_sales: Optional[float] = None  # None = no sales data loaded for this product yet
    primary_region: Optional[str] = None
    viral_trend: Optional[str] = None  # None = nothing documented, not "no viral trend happened"
    source_url: Optional[str] = None
    data_source: Optional[str] = None

    class Config:
        from_attributes = True


class SalesPoint(BaseModel):
    period_date: date
    region: str
    units_sold: float

    class Config:
        from_attributes = True


class ForecastPoint(BaseModel):
    period_date: date
    region: str
    predicted_units: float
    lo_80: Optional[float] = None
    hi_80: Optional[float] = None
    model_name: str

    class Config:
        from_attributes = True


class SeasonalInsight(BaseModel):
    region: str
    peak_month: Optional[int] = None
    peak_avg_units: Optional[float] = None
    trough_month: Optional[int] = None
    trough_avg_units: Optional[float] = None


class ProductDetail(BaseModel):
    product: ProductOut
    history: List[SalesPoint]
    forecast: List[ForecastPoint]
    seasonality: List[SeasonalInsight]


class IngestSummary(BaseModel):
    products_loaded: int
    sales_records_loaded: int
    warnings: List[str] = []


class SearchResult(BaseModel):
    product: ProductOut
    score: float


class TrendSeries(BaseModel):
    keyword: str
    dates: List[date]
    interest: List[int]  # Google Trends "relative interest", 0-100


class TrendsResponse(BaseModel):
    available: bool
    reason: Optional[str] = None  # set when available=False, e.g. network/rate-limit error
    timeframe: Optional[str] = None
    series: List[TrendSeries] = []


class SamplePost(BaseModel):
    text: str
    url: str
    author: str


class TrendSignalOut(BaseModel):
    id: int
    keyword: str
    category: Optional[str] = None
    window_start: date
    window_end: date
    mention_count: int
    baseline_mean: float
    baseline_std: float
    z_score: float
    trends_corroborated: Optional[str] = None
    sample_posts: List[SamplePost] = []
    status: str
    confirmed_product_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime
    matching_products: List[ProductOut] = []  # populated by the API, not stored

    class Config:
        from_attributes = True


class ScanSummary(BaseModel):
    keywords_checked: List[str]
    signals_created: int
    reason: Optional[str] = None  # set if Bluesky wasn't reachable at all


class ConfirmSignalRequest(BaseModel):
    product_id: int
    note: Optional[str] = None


class DashboardSummary(BaseModel):
    total_products: int
    products_with_sales_data: int
    products_without_sales_data: int
    top_products_by_baseline: List[ProductOut]
    pending_signals: int = 0
