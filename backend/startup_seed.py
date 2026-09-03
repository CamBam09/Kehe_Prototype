"""
Idempotent startup seeding, run once before uvicorn starts.

Free hosting tiers (e.g. Render's free web service) don't give SQLite a
persistent disk, so every fresh deploy/restart starts from an empty
database. Rather than land on a blank dashboard, this loads the real
70-product KeHE catalog and the synthetic demo catalog/sales/signals
(same data `README.md` walks through by hand) so the live app is
immediately useful. It only runs when the products table is empty, so it
never overwrites real data someone has since uploaded.

Set SKIP_STARTUP_SEED=1 to disable (e.g. once you're on Postgres with
real data and don't want this to ever run).
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent

from app.database import SessionLocal, engine, Base  # noqa: E402
from app import models, ingestion, forecasting  # noqa: E402


def already_seeded() -> bool:
    db = SessionLocal()
    try:
        return db.query(models.Product).first() is not None
    finally:
        db.close()


def main():
    if os.environ.get("SKIP_STARTUP_SEED") == "1":
        print("startup_seed: SKIP_STARTUP_SEED=1, skipping")
        return

    Base.metadata.create_all(bind=engine)

    if already_seeded():
        print("startup_seed: products already present, skipping")
        return

    print("startup_seed: empty database, loading demo + real KeHE catalog data")

    # (Re)generate the synthetic demo catalog/sales CSVs.
    subprocess.run([sys.executable, str(BACKEND_DIR / "seed_demo_data.py")], check=True, cwd=BACKEND_DIR)

    db = SessionLocal()
    try:
        catalog_demo = (BACKEND_DIR / "data" / "catalog_demo.csv").read_bytes()
        sales_demo = (BACKEND_DIR / "data" / "sales_demo.csv").read_bytes()
        kehe_products = (BACKEND_DIR / "data" / "kehe_products.csv").read_bytes()

        n, warnings = ingestion.ingest_catalog_csv(db, catalog_demo)
        print(f"startup_seed: loaded {n} synthetic demo products", warnings)
        n, warnings = ingestion.ingest_sales_csv(db, sales_demo)
        print(f"startup_seed: loaded {n} synthetic demo sales rows", warnings)
        n, warnings = ingestion.ingest_catalog_csv(db, kehe_products)
        print(f"startup_seed: loaded {n} real KeHE products", warnings)

        product_ids = [p.id for p in db.query(models.Product.id).all()]
        forecasted = 0
        for pid in product_ids:
            if forecasting.generate_forecast(db, pid, periods=6):
                forecasted += 1
        print(f"startup_seed: generated forecasts for {forecasted} products")
    finally:
        db.close()

    # Fictional example viral-moment signals, since a live Bluesky scan needs
    # network access this host may or may not have — see README.
    subprocess.run([sys.executable, str(BACKEND_DIR / "seed_demo_signals.py")], check=True, cwd=BACKEND_DIR)
    print("startup_seed: done")


if __name__ == "__main__":
    main()
