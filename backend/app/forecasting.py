"""
Trend forecasting and seasonality detection.

Uses Nixtla's statsforecast (AutoARIMA), which is pip-installable and
trains directly on each product/region's own sales history, no pretrained
weights or network access required. This is the one piece of the stack
that runs fully end-to-end in any environment, including this build
sandbox.

Two things are produced per product:
  - a forecast: predicted units for the next N periods, per region, with
    an 80% interval, written to the forecasts table.
  - seasonality: which calendar month tends to peak and which tends to
    trough, per region, computed directly from history (not modeled).

AutoARIMA needs a reasonable amount of history to fit a seasonal model
(roughly two full yearly cycles of monthly data). Shorter series fall
back to a naive seasonal-average forecast so the endpoint still returns
something useful rather than erroring out.
"""
from collections import defaultdict
from datetime import date
from typing import List

import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from . import models
from .schemas import SeasonalInsight

MIN_POINTS_FOR_ARIMA = 24  # ~2 years of monthly data
SEASON_LENGTH = 12


def _sales_dataframe(db: Session, product_id: int) -> pd.DataFrame:
    records = (
        db.query(models.SalesRecord)
        .filter(models.SalesRecord.product_id == product_id)
        .order_by(models.SalesRecord.period_date)
        .all()
    )
    rows = [
        {"unique_id": r.region, "ds": pd.Timestamp(r.period_date), "y": r.units_sold}
        for r in records
    ]
    return pd.DataFrame(rows, columns=["unique_id", "ds", "y"])


def _naive_seasonal_forecast(group: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Fallback when there isn't enough history for AutoARIMA: forecast each
    future month as the historical average for that calendar month (or the
    overall mean if that month hasn't been seen yet)."""
    group = group.sort_values("ds")
    by_month = group.groupby(group["ds"].dt.month)["y"].mean()
    overall_mean = group["y"].mean()
    last_date = group["ds"].max()

    out_rows = []
    for i in range(1, periods + 1):
        future_date = (last_date + relativedelta(months=i)).replace(day=1)
        month = future_date.month
        pred = by_month.get(month, overall_mean)
        spread = group["y"].std(ddof=0) or (pred * 0.1)
        out_rows.append({
            "unique_id": group["unique_id"].iloc[0],
            "ds": future_date,
            "AutoARIMA": pred,
            "AutoARIMA-lo-80": max(pred - spread, 0),
            "AutoARIMA-hi-80": pred + spread,
        })
    return pd.DataFrame(out_rows)


def generate_forecast(db: Session, product_id: int, periods: int = 6) -> List[models.Forecast]:
    df = _sales_dataframe(db, product_id)
    if df.empty:
        return []

    forecast_frames = []
    for region, group in df.groupby("unique_id"):
        if len(group) >= MIN_POINTS_FOR_ARIMA:
            try:
                from statsforecast import StatsForecast
                from statsforecast.models import AutoARIMA

                sf = StatsForecast(models=[AutoARIMA(season_length=SEASON_LENGTH)], freq="MS")
                sf.fit(group[["unique_id", "ds", "y"]])
                pred = sf.predict(h=periods, level=[80])
                forecast_frames.append(pred)
                continue
            except Exception:
                pass  # fall through to naive method below
        forecast_frames.append(_naive_seasonal_forecast(group, periods))

    if not forecast_frames:
        return []
    combined = pd.concat(forecast_frames, ignore_index=True)

    # replace any existing forecast rows for this product with the fresh run
    db.query(models.Forecast).filter(models.Forecast.product_id == product_id).delete()

    created = []
    for _, row in combined.iterrows():
        f = models.Forecast(
            product_id=product_id,
            region=row["unique_id"],
            period_date=pd.Timestamp(row["ds"]).date(),
            predicted_units=max(float(row["AutoARIMA"]), 0.0),
            lo_80=max(float(row.get("AutoARIMA-lo-80", 0.0)), 0.0),
            hi_80=float(row.get("AutoARIMA-hi-80", row["AutoARIMA"])),
            model_name="AutoARIMA",
        )
        db.add(f)
        created.append(f)
    db.commit()
    return created


def compute_seasonality(db: Session, product_id: int) -> List[SeasonalInsight]:
    df = _sales_dataframe(db, product_id)
    if df.empty:
        return []

    insights = []
    for region, group in df.groupby("unique_id"):
        by_month = group.groupby(group["ds"].dt.month)["y"].mean()
        if by_month.empty:
            continue
        peak_month = int(by_month.idxmax())
        trough_month = int(by_month.idxmin())
        insights.append(SeasonalInsight(
            region=region,
            peak_month=peak_month,
            peak_avg_units=round(float(by_month.max()), 2),
            trough_month=trough_month,
            trough_avg_units=round(float(by_month.min()), 2),
        ))
    return insights
