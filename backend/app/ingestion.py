"""
Catalog ingestion.

Two paths are supported:

1. ingest_catalog_csv / ingest_sales_csv - works today, no external
   dependencies. This is the path for KeHe catalogs and sales history
   that already exist as spreadsheets or exports from their systems
   (the common case for a distributor's internal data).

2. ingest_catalog_document - for catalogs that only exist as PDFs, scans,
   or photographed product sheets. This routes through Docling, and for
   complex/scanned layouts Docling calls a vision-language model as its
   parsing backend; Granite-Docling-258M (ibm-granite/granite-docling-258M
   on Hugging Face) is the model built for that role. That model's weights
   could not be downloaded from this build environment because outbound
   access to huggingface.co is not on this sandbox's network allowlist,
   so this path is wired up but not exercised here. To activate it:
     pip install docling
     (ensure ibm-granite/granite-docling-258M is reachable, e.g. run this
     on a machine/environment with normal internet access, or point
     Docling at a local copy of the weights)
   and remove the NotImplementedError below.
"""
import csv
import io
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from . import models


def _parse_date(value: str):
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y"):
        try:
            d = datetime.strptime(value, fmt)
            if fmt == "%Y-%m":
                d = d.replace(day=1)
            return d.date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {value!r} (use YYYY-MM-DD or YYYY-MM)")


def ingest_catalog_csv(db: Session, file_bytes: bytes) -> tuple[int, List[str]]:
    """
    Required columns: sku, name
    Optional columns: brand, category, description, baseline_sales, primary_region,
                       viral_trend, source_url, data_source
    Upserts by sku. baseline_sales is left as None (not 0) when the column is
    missing or blank, since "we don't have sales data for this yet" and
    "this product sells zero units" are different facts and the dashboard
    needs to tell them apart.
    """
    warnings: List[str] = []
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"sku", "name"}
    if not required.issubset(set(h.strip() for h in (reader.fieldnames or []))):
        raise ValueError(f"Catalog CSV must include at least columns: {sorted(required)}")

    count = 0
    for row_num, row in enumerate(reader, start=2):
        sku = (row.get("sku") or "").strip()
        name = (row.get("name") or "").strip()
        if not sku or not name:
            warnings.append(f"Row {row_num}: missing sku or name, skipped")
            continue

        existing = db.query(models.Product).filter(models.Product.sku == sku).first()
        baseline_raw = (row.get("baseline_sales") or "").strip()
        baseline = None
        if baseline_raw:
            try:
                baseline = float(baseline_raw)
            except ValueError:
                warnings.append(f"Row {row_num}: bad baseline_sales {baseline_raw!r}, left blank")

        data_source = (row.get("data_source") or "").strip() or "user_upload"

        if existing:
            existing.name = name
            existing.brand = (row.get("brand") or existing.brand or "").strip() or None
            existing.category = (row.get("category") or existing.category or "").strip() or None
            existing.description = (row.get("description") or existing.description or "").strip()
            if baseline is not None:
                existing.baseline_sales = baseline
            existing.primary_region = (row.get("primary_region") or existing.primary_region or "").strip() or None
            existing.viral_trend = (row.get("viral_trend") or existing.viral_trend or "").strip() or None
            existing.source_url = (row.get("source_url") or existing.source_url or "").strip() or None
            existing.data_source = data_source
        else:
            db.add(models.Product(
                sku=sku,
                name=name,
                brand=(row.get("brand") or "").strip() or None,
                category=(row.get("category") or "").strip() or None,
                description=(row.get("description") or "").strip(),
                baseline_sales=baseline,
                primary_region=(row.get("primary_region") or "").strip() or None,
                viral_trend=(row.get("viral_trend") or "").strip() or None,
                source_url=(row.get("source_url") or "").strip() or None,
                data_source=data_source,
            ))
        count += 1

    db.commit()
    return count, warnings


def ingest_sales_csv(db: Session, file_bytes: bytes) -> tuple[int, List[str]]:
    """
    Expected columns: sku, region, period_date, units_sold
    period_date accepts YYYY-MM-DD or YYYY-MM (treated as the 1st of the month).
    """
    warnings: List[str] = []
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"sku", "region", "period_date", "units_sold"}
    if not required.issubset(set(h.strip() for h in (reader.fieldnames or []))):
        raise ValueError(f"Sales CSV must include columns: {sorted(required)}")

    sku_to_id = {p.sku: p.id for p in db.query(models.Product).all()}
    count = 0
    for row_num, row in enumerate(reader, start=2):
        sku = (row.get("sku") or "").strip()
        product_id = sku_to_id.get(sku)
        if product_id is None:
            warnings.append(f"Row {row_num}: unknown sku {sku!r}, skipped (load the catalog first)")
            continue
        try:
            period_date = _parse_date(row.get("period_date") or "")
        except ValueError as e:
            warnings.append(f"Row {row_num}: {e}")
            continue
        try:
            units = float(row.get("units_sold"))
        except (TypeError, ValueError):
            warnings.append(f"Row {row_num}: bad units_sold, skipped")
            continue

        region = (row.get("region") or "").strip() or "UNKNOWN"
        existing = (
            db.query(models.SalesRecord)
            .filter(
                models.SalesRecord.product_id == product_id,
                models.SalesRecord.region == region,
                models.SalesRecord.period_date == period_date,
            )
            .first()
        )
        if existing:
            existing.units_sold = units
        else:
            db.add(models.SalesRecord(
                product_id=product_id, region=region, period_date=period_date, units_sold=units
            ))
        count += 1

    db.commit()
    return count, warnings


def ingest_catalog_document(file_bytes: bytes, filename: str):
    """
    PDF / scanned catalog ingestion path via Docling (+ Granite-Docling-258M
    for the hardest layouts). See module docstring: not runnable in this
    sandbox because huggingface.co is unreachable here.

    Once docling is installed and the model is reachable, this becomes:

        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(io.BytesIO(file_bytes))
        markdown = result.document.export_to_markdown()
        # then parse `markdown`'s tables into the same
        # (sku, name, category, description, baseline_sales, primary_region)
        # shape ingest_catalog_csv expects, and call ingest_catalog_csv-style
        # upserts with the parsed rows.
    """
    raise NotImplementedError(
        "Document/PDF catalog parsing requires Docling + Granite-Docling-258M, "
        "which need model weights from huggingface.co. That host is not reachable "
        "from this environment. Install `docling` and run this path in an "
        "environment with normal internet access, or export the catalog to CSV "
        "and use /ingest/catalog instead."
    )
