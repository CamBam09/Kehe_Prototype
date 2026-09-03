"""
Generates a small SYNTHETIC example catalog and sales history so the tool
can be tried out before connecting real KeHe data. Nothing here is real
sales data, real product data, or tied to any actual KeHe customer or
region; it's fabricated on purpose, with obviously fake numbers, purely to
exercise the ingestion/search/forecasting pipeline end to end.

Usage:
    python3 seed_demo_data.py
Writes catalog_demo.csv and sales_demo.csv into ../data/
"""
import csv
import math
import random
from datetime import date
from pathlib import Path

random.seed(7)

OUT_DIR = Path(__file__).resolve().parent / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REGIONS = ["Northeast", "Midwest", "South", "West"]

# (sku, name, category, description, baseline_sales, primary_region, seasonal_peak_month,
#  amplitude, viral_trend)
# viral_trend is blank for most rows on purpose: this field documents a real, known
# viral moment when someone enters one, it isn't auto-generated. The two examples
# below are FICTIONAL, invented for this demo only, to show what the field looks
# like when filled in.
PRODUCTS = [
    ("DEMO-BEV-001", "Sparkling Citrus Water 12pk", "Beverages", "Lightly carbonated citrus-flavored water, 12oz cans", 1200, "South", 7, 0.6, ""),
    ("DEMO-BEV-002", "Cold Brew Coffee Concentrate", "Beverages", "Shelf-stable cold brew concentrate, 32oz bottle", 800, "Northeast", 6, 0.4, ""),
    ("DEMO-SOUP-001", "Organic Butternut Squash Soup", "Soups", "Ready-to-heat organic soup, 24oz carton", 950, "Midwest", 11, 0.7, ""),
    ("DEMO-SOUP-002", "Chicken Tortilla Soup", "Soups", "Shelf-stable soup, 15oz can", 700, "South", 1, 0.5, ""),
    ("DEMO-SNACK-001", "Sea Salt Kettle Chips", "Snacks", "Small-batch kettle-cooked potato chips, 5oz bag", 1500, "West", 9, 0.2,
     "FICTIONAL EXAMPLE - TikTok, Sept 2025: an 'ASMR kettle chip crunch' trend tagged this brand, illustrative only."),
    ("DEMO-SNACK-002", "Dark Chocolate Trail Mix", "Snacks", "Trail mix with dark chocolate and almonds, 10oz pouch", 640, "Northeast", 12, 0.3, ""),
    ("DEMO-FROZ-001", "Frozen Mango Chunks", "Frozen", "IQF frozen mango, 16oz bag", 900, "West", 7, 0.5, ""),
    ("DEMO-FROZ-002", "Frozen Veggie Burger Patties", "Frozen", "Plant-based burger patties, 4-count box", 1100, "Midwest", 6, 0.35, ""),
    ("DEMO-BAKE-001", "Pumpkin Spice Muffin Mix", "Bakery", "Shelf-stable baking mix, 16oz box", 500, "Midwest", 10, 0.9,
     "FICTIONAL EXAMPLE - Instagram, Oct 2024: a home-baking creator's muffin-mix hack reel was widely shared, illustrative only."),
    ("DEMO-BAKE-002", "Sourdough Sandwich Bread", "Bakery", "Par-baked sourdough loaf, frozen case of 8", 1050, "Northeast", 3, 0.15, ""),
]


def seasonal_units(baseline, peak_month, amplitude, month, year_index, noise_scale=0.08):
    # cosine wave peaking at `peak_month`, plus a mild year-over-year growth trend, plus noise
    angle = 2 * math.pi * (month - peak_month) / 12
    seasonal_factor = 1 + amplitude * math.cos(angle)
    growth = 1 + 0.03 * year_index
    noise = 1 + random.uniform(-noise_scale, noise_scale)
    return max(round(baseline * seasonal_factor * growth * noise), 0)


def main():
    catalog_path = OUT_DIR / "catalog_demo.csv"
    sales_path = OUT_DIR / "sales_demo.csv"

    with open(catalog_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "name", "category", "description", "baseline_sales", "primary_region", "viral_trend", "data_source"])
        for sku, name, category, desc, baseline, region, _peak, _amp, viral_trend in PRODUCTS:
            writer.writerow([sku, name, category, desc, baseline, region, viral_trend, "synthetic_demo"])

    with open(sales_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "region", "period_date", "units_sold"])
        start_year, end_year = 2023, 2026  # 3+ years of monthly history
        for sku, name, category, desc, baseline, primary_region, peak_month, amplitude, _viral in PRODUCTS:
            # sells everywhere but strongest in its primary region; give every region a history
            for region in REGIONS:
                region_multiplier = 1.0 if region == primary_region else random.uniform(0.35, 0.7)
                year_index = 0
                for year in range(start_year, end_year + 1):
                    for month in range(1, 13):
                        if year == end_year and month > 8:  # stop at "today" (Sep 2026)
                            continue
                        units = seasonal_units(baseline * region_multiplier, peak_month, amplitude, month, year_index)
                        writer.writerow([sku, region, date(year, month, 1).isoformat(), units])
                    year_index += 1

    print(f"Wrote {catalog_path}")
    print(f"Wrote {sales_path}")


if __name__ == "__main__":
    main()
