"""
Idempotent startup seeding.

Free hosting tiers (e.g. Render's free web service) don't give SQLite a
persistent disk, so every cold start after a spin-down begins from an
empty database. Rather than land on a blank dashboard, this loads the
real 70-product KeHE catalog and the synthetic demo catalog/sales
(same data `README.md` walks through by hand) so the live app is
immediately useful. It only runs when the products table is empty, so it
never overwrites real data someone has since uploaded.

`run_seed_in_background()` is called from `main.py`'s FastAPI startup
event via a daemon thread, deliberately NOT awaited: on a slow/free-tier
CPU, fitting a forecast model per product can take well over a minute,
and blocking uvicorn's own startup on that would mean the port never
opens and every cold start looks like a hang/timeout to whoever's
waiting on it. Catalog/sales rows (cheap) land within seconds; forecasts
(expensive) are also generated here but the app is already serving
requests while that finishes. Seasonality/forecast charts for products
just show as pending until then, or a person can also fire it manually
via "Forecast all products" in the UI.

Set SKIP_STARTUP_SEED=1 to disable (e.g. once you're on Postgres with
real data and don't want this to ever run).

Usage: `python3 startup_seed.py` also runs it once, synchronously, for
local/manual use (e.g. re-seeding a local SQLite file by hand).
"""
import os
import threading
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


def _generate_demo_csvs():
    import runpy
    runpy.run_path(str(BACKEND_DIR / "seed_demo_data.py"), run_name="__main__")


def run_seed() -> None:
    if os.environ.get("SKIP_STARTUP_SEED") == "1":
        print("startup_seed: SKIP_STARTUP_SEED=1, skipping")
        return

    Base.metadata.create_all(bind=engine)

    if already_seeded():
        print("startup_seed: products already present, skipping")
        return

    print("startup_seed: empty database, loading demo + real KeHE catalog data")

    try:
        _generate_demo_csvs()

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

        # Fictional example viral-moment signals, since a live Bluesky scan
        # needs network access this host may or may not have — see README.
        import runpy
        runpy.run_path(str(BACKEND_DIR / "seed_demo_signals.py"), run_name="__main__")
    except Exception as e:  # noqa: BLE001 - never take the app down over seeding
        print(f"startup_seed: failed, app will start with an empty catalog: {e!r}")


def run_seed_in_background() -> None:
    threading.Thread(target=run_seed, name="startup-seed", daemon=True).start()


if __name__ == "__main__":
    run_seed()
