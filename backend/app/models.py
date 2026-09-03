"""
Core data model.

products        - the catalog: one row per SKU, with baseline sales and
                  the geography where it typically sells.
sales_records   - historical time series: units sold per product, per
                  region, per period. This is what seasonality detection
                  and forecasting are computed from.
forecasts       - model output: predicted future units per product/region,
                  written by the forecasting job, read by the API/frontend.
"""
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False, index=True)
    brand = Column(String, index=True)
    category = Column(String, index=True)
    description = Column(Text, default="")
    baseline_sales = Column(Float, nullable=True)  # None = not known yet, not "zero"
    primary_region = Column(String, index=True)  # where it typically sells best
    # Free text, entered by whoever uploads the catalog: if/when a viral social
    # media moment affected this product's sales (e.g. "TikTok - Nov 2025:
    # cranberry sauce recipe videos, baseline roughly doubled for 3 weeks").
    # This is documented by a person, not detected automatically: nothing in
    # this tool scores social feeds for virality (see trends.py's docstring
    # for why, and what a real version of that would need). None = nothing
    # documented, not "no viral trend happened."
    viral_trend = Column(Text, nullable=True)
    source_url = Column(String)  # link back to where the product record came from, if any
    # where this row's data came from, so the UI can be honest about what is/isn't real
    # sales data: "synthetic_demo", "kehe_public_marketing_page", "user_upload", ...
    data_source = Column(String, default="user_upload")
    created_at = Column(DateTime, default=datetime.utcnow)

    sales_records = relationship(
        "SalesRecord", back_populates="product", cascade="all, delete-orphan"
    )
    forecasts = relationship(
        "Forecast", back_populates="product", cascade="all, delete-orphan"
    )


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        UniqueConstraint("product_id", "region", "period_date", name="uq_sales_period"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    region = Column(String, nullable=False, index=True)
    period_date = Column(Date, nullable=False, index=True)  # first day of the period (monthly)
    units_sold = Column(Float, nullable=False)

    product = relationship("Product", back_populates="sales_records")


class TrendSignal(Base):
    """A candidate viral moment detected by the signals scan (bluesky.py +
    spike detection), NOT a confirmed fact. Starts as needs_review; a person
    either confirms it (which appends a note to a specific product's
    viral_trend field) or dismisses it as noise. See signals.py."""
    __tablename__ = "trend_signals"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, nullable=False, index=True)
    category = Column(String, index=True)  # catalog category this keyword was drawn from, if any
    window_start = Column(Date, nullable=False)
    window_end = Column(Date, nullable=False)
    mention_count = Column(Integer, nullable=False)  # recent-window post count (bounded, see bluesky.py)
    baseline_mean = Column(Float, nullable=False)
    baseline_std = Column(Float, nullable=False)
    z_score = Column(Float, nullable=False)
    trends_corroborated = Column(String)  # "yes" / "no" / "unavailable" (Google Trends couldn't be checked)
    sample_posts = Column(Text)  # JSON list of up to 3 {text, url, author} for a human to sanity-check
    status = Column(String, default="needs_review", index=True)  # needs_review / confirmed / dismissed
    confirmed_product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    confirmed_product = relationship("Product")


class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    region = Column(String, nullable=False, index=True)
    period_date = Column(Date, nullable=False, index=True)  # future period
    predicted_units = Column(Float, nullable=False)
    lo_80 = Column(Float)  # 80% confidence interval, lower bound
    hi_80 = Column(Float)  # 80% confidence interval, upper bound
    model_name = Column(String, default="AutoARIMA")
    generated_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="forecasts")
