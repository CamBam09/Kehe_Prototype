"""
Builds data/kehe_products.csv from the real product rows in the
"KeHE_Retailers_Brands" Google Sheet (Brand Products (Detail) tab), which
covers ~10 brands spotlighted on KeHE's public retailers page
(https://www.kehe.com/retailers/), pulled from each brand's own storefront.

This is NOT KeHE's internal ~8,500-brand catalog and carries NO sales
figures: that data lives behind KeHE's login-gated CONNECT Retailer portal
and was never available to pull from. Every row here is tagged
data_source=kehe_public_marketing_page and has no baseline_sales or
primary_region, on purpose, so the app shows these products honestly as
"catalog entry, no sales data yet" rather than inventing numbers.

`category` is a food-type label derived here by matching keywords in the
product name, since the sheet itself only has a marketing "program"
category (KeHE Exclusive Brand / New & Emerging / Established Favorite),
not a food category. It exists so these real products can drive the
Trends dashboard's keyword list.

Re-run this any time the source sheet is updated; it fully regenerates
the CSV (upserts by sku on ingestion, so re-running the ingest endpoint
afterward is also safe).
"""
import csv
import re
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "data" / "kehe_products.csv"

# (brand, product_name, source_url) -- pulled from the Brand Products (Detail)
# tab of the KeHE_Retailers_Brands sheet. The one non-food row (a lipstick
# collaboration product from Nice Cans) is intentionally excluded.
PRODUCTS = [
    ("CADIA", "Kosher Baby Dill Pickles", "https://mycadia.com/product/baby-dill-pickles/"),
    ("CADIA", "Organic Creamy Carrot Coconut Soup", "https://mycadia.com/product/creamy-carrot-coconut-soup/"),
    ("CADIA", "Sea Salt Veggie Straws", "https://mycadia.com/product/veggie-straws/"),
    ("CADIA", "Kosher Whole Dill Pickles", "https://mycadia.com/product/whole-dill-pickles/"),
    ("CADIA", "Kosher Dill Pickle Spears", "https://mycadia.com/product/kosher-dill-pickle-spears/"),
    ("CADIA", "Canned Organic Crushed Tomatoes with Basil", "https://mycadia.com/product/organic-crushed-tomatoes/"),
    ("CADIA", "Organic Canned Diced Tomatoes", "https://mycadia.com/product/canned-diced-tomatoes/"),
    ("CADIA", "Organic Creamy Mushroom Soup", "https://mycadia.com/product/organic-mushroom-soup/"),
    ("CADIA", "Chicken Nuggets", "https://mycadia.com/product/natural-chicken-nuggets/"),
    ("CADIA", "Jalapeno Veggie Straws", "https://mycadia.com/product/jalapeno-veggie-straws/"),
    ("CADIA", "Kosher Dill Pickle Relish", "https://mycadia.com/product/dill-pickle-relish/"),
    ("CADIA", "Organic Tomato Paste - All Natural", "https://mycadia.com/product/organic-tomato-paste/"),
    ("CADIA", "Organic Tomato Sauce - All Natural", "https://mycadia.com/product/organic-tomato-sauce/"),
    ("MADE-WITH", "Organic Light Agave Nectar Syrup - Non-GMO", "https://madewithfoods.com/product/light-agave-syrup/"),
    ("MADE-WITH", "Organic Mayonnaise - Classic - Non GMO", "https://madewithfoods.com/product/organic-mayonnaise/"),
    ("MADE-WITH", "Organic Agave Syrup - Non-GMO", "https://madewithfoods.com/product/organic-agave-syrup/"),
    ("MADE-WITH", "Creamy Italian Cheese", "https://madewithfoods.com/product/creamy-italian-cheese/"),
    ("MADE-WITH", "Tomato Basil Organic Pasta Sauce", "https://madewithfoods.com/product/organic-pasta-sauce/"),
    ("MADE-WITH", "All Natural Organic Amber Maple Syrup", "https://madewithfoods.com/product/organic-amber-maple-syrup/"),
    ("MADE-WITH", "Italian Cappuccino Gelato", "https://madewithfoods.com/product/italian-cappuccino-gelato/"),
    ("MADE-WITH", "All Natural Organic Tomato Sauce", "https://madewithfoods.com/product/organic-tomato-sauce/"),
    ("MADE-WITH", "Italian Pistachio Gelato", "https://madewithfoods.com/product/italian-pistachio-gelato/"),
    ("MADE-WITH", "Habanero Roasted Corn Kernels", "https://madewithfoods.com/product/roasted-corn-kernels/"),
    ("MADE-WITH", "Organic Olive Oil Spray", "https://madewithfoods.com/product/organic-olive-oil-spray/"),
    ("MADE-WITH", "Organic Red Kidney Beans", "https://madewithfoods.com/product/organic-red-kidney-beans/"),
    ("MADE-WITH", "Organic Garlic Infused Olive Oil Spray", "https://madewithfoods.com/product/garlic-infused-olive-oil-spray/"),
    ("MADE-WITH", "Organic Balsamic Glaze of Modena", "https://madewithfoods.com/product/organic-balsamic-glaze/"),
    ("MADE-WITH", "Organic Honey Almond Granola - Non GMO", "https://madewithfoods.com/product/honey-almond-granola/"),
    ("MADE-WITH", "Pineapple Jalapeno Jelly", "https://madewithfoods.com/product/pineapple-jalapeno-jelly/"),
    ("MADE-WITH", "All Natural Organic No Salt Added Diced Tomatoes", "https://madewithfoods.com/product/no-salt-added-diced-tomatoes/"),
    ("Einstein Energy", "Chocolate Peanut Butter (18-Count)", "https://einstein.energy/products/chocolate-peanut-butter"),
    ("Einstein Energy", "Chocolate Peanut Butter (9-Count Box)", "https://einstein.energy/products/chocolate-peanut-butter-9-count-box"),
    ("Einstein Energy", "Double Chocolate (18-Count Box)", "https://einstein.energy/products/double-chocolate-18-count-box"),
    ("Einstein Energy", "Double Chocolate (9-Count Box)", "https://einstein.energy/products/double-chocolate-9-count-box"),
    ("Einstein Energy", "Combo Pack - Chocolate Peanut Butter & Double Chocolate (18-Count)", "https://einstein.energy/products/einstein-super-snack-bar-combo-pack-chocolate-peanut-butter-double-chocolate-18-count"),
    ("Einstein Energy", "Einstein Energy Smart Snack Bars", "https://einstein.energy/products/einstein-energy-bars"),
    ("Lil Hala Foods", "Free-Range Mediterranean Style Chicken (6 Count)", "https://lilhalafoods.com/products/free-range-mediterranean-style-chicken"),
    ("Lil Hala Foods", "Grass-Fed Beef Shawarma (6 Count)", "https://lilhalafoods.com/products/grass-fed-beef-shawarma"),
    ("Lil Hala Foods", "Free-Range Chicken Curry (6 Count)", "https://lilhalafoods.com/products/free-range-chicken-curry"),
    ("Lil Hala Foods", "Grass-Fed Roast Beef (6 Count)", "https://lilhalafoods.com/products/grass-fed-roast-beef"),
    ("Lil Hala Foods", "Free-Range Jerk Chicken (6 Count)", "https://lilhalafoods.com/products/free-range-jerk-chicken"),
    ("Lil Hala Foods", "Best Seller Bundle (12 Count)", "https://lilhalafoods.com/products/best-seller-bundle-12-count"),
    ("Nice Cans", "Sardines with Rosemary and Fennel", "https://justnicecans.com/products/sardines-with-rosemary-and-fennel"),
    ("Nice Cans", "Sardines in Tomatoes and Peppers", "https://justnicecans.com/products/sardines-in-tomatoes-and-peppers"),
    ("Nice Cans", "Smoked Sardines in Organic Olive Oil and Sea Salt", "https://justnicecans.com/products/smoked-sardines-in-organic-olive-oil-and-sea-salt"),
    ("Nice Cans", "Variety Pack", "https://justnicecans.com/products/variety-pack"),
    ("Pastaio", "Organic Durum Wheat Penne (8-Pack)", "https://firmas-rep.myshopify.com/collections/all/products/organic-durum-wheat-penne"),
    ("Pastaio", "Organic Durum Wheat Rotini (8-Pack)", "https://firmas-rep.myshopify.com/collections/all/products/organic-durum-wheat-rotini"),
    ("Pastaio", "Organic Durum Wheat Spaghetti (8-Pack)", "https://firmas-rep.myshopify.com/collections/all/products/organic-durum-wheat-spaghetti"),
    ("Tierra Negra Salsa", "Premium Mexican Dark Salsa (Signature)", "https://www.tierranegrasalsa.com/product/salsa-original/"),
    ("Tierra Negra Salsa", "Premium Mexican Salsa Roja", "https://www.tierranegrasalsa.com/product/premium-mexican-salsa-roja/"),
    ("Tierra Negra Salsa", "Premium Mexican Salsa Verde", "https://www.tierranegrasalsa.com/product/premium-mexican-salsa-verde/"),
    ("Tierra Negra Salsa", "Premium Mexican Salsa Bundle", "https://www.tierranegrasalsa.com/product/salsa-bundle/"),
    ("Onoin", "Global Variety Pack", "https://eatonoin.com/products/variety-pack"),
    ("Onoin", "Garlic & Herb", "https://eatonoin.com/products/garlic-herb"),
    ("Onoin", "Original", "https://eatonoin.com/products/original"),
    ("Onoin", "Ginger & Lemongrass", "https://eatonoin.com/products/ginger-lemongrass"),
    ("Onoin", "Jalapeno Lime", "https://eatonoin.com/products/jalapeno-lime"),
    ("Hella Cocktail Co.", "Aromatic Bitters, 5 oz", "https://hellacocktail.co/products/aromatic-cocktail-bitters-5oz"),
    ("Hella Cocktail Co.", "Mexican Chocolate Bitters, 5 oz", "https://hellacocktail.co/products/mexican-chocolate-cocktail-bitters-5oz"),
    ("Hella Cocktail Co.", "Citrus Bitters, 1.7 oz", "https://shop.hellacocktail.co/products/citrus-bitters-1-7oz"),
    ("Hella Cocktail Co.", "Five Flavor Bitters Starter Kit, 8.5 oz", "https://hellacocktail.co/products/five-flavor-bitters-bar-set-five-1-7-oz-bottles"),
    ("Hella Cocktail Co.", "Two Flavor Bitters Starter Kit, 3.4 oz", "https://hellacocktail.co/products/two-flavor-bitters-bar-set-two-1-7-ounce-bottles"),
    ("Di Martino Pasta", "Spaghetti (PGI Gragnano)", "https://pastadimartino.com/products/spaghetti"),
    ("Di Martino Pasta", "Organic Spaghetti", "https://pastadimartino.com/products/spaghetti-organic"),
    ("Di Martino Pasta", "Macaroni (PGI Gragnano)", "https://pastadimartino.com/products/macaroni"),
    ("Di Martino Pasta", "Bucatini (PGI Gragnano)", "https://pastadimartino.com/products/bucatini"),
    ("Di Martino Pasta", "Linguine (PGI Gragnano)", "https://pastadimartino.com/products/linguine"),
    ("Di Martino Pasta", "Manicotti (PGI Gragnano)", "https://pastadimartino.com/products/manicotti"),
    ("Di Martino Pasta", "Orzo (PGI Gragnano)", "https://pastadimartino.com/products/orzo"),
]

# Ordered so more specific terms are checked before generic ones.
CATEGORY_RULES = [
    ("Pickles", ["pickle", "relish"]),
    ("Soup", ["soup"]),
    ("Snacks", ["veggie straws", "kettle", "chip"]),
    ("Canned Tomatoes", ["tomato paste", "tomato sauce", "diced tomatoes", "crushed tomatoes"]),
    ("Frozen/Prepared Entrees", ["chicken nuggets"]),
    ("Syrups", ["agave", "maple syrup"]),
    ("Condiments", ["mayonnaise", "balsamic glaze"]),
    ("Cheese", ["cheese"]),
    ("Pasta Sauce", ["pasta sauce"]),
    ("Frozen Desserts", ["gelato"]),
    ("Canned Vegetables", ["corn kernels", "kidney beans"]),
    ("Oils & Sprays", ["olive oil"]),
    ("Granola", ["granola"]),
    ("Spreads & Jellies", ["jelly"]),
    ("Energy Bars", ["chocolate peanut butter", "double chocolate", "combo pack", "snack bars"]),
    ("Baby/Kids Food", ["free-range", "grass-fed", "bundle (12 count)"]),
    ("Canned Seafood", ["sardine"]),
    ("Variety Pack", ["variety pack"]),
    ("Pasta", ["penne", "rotini", "spaghetti", "macaroni", "bucatini", "linguine", "manicotti", "orzo"]),
    ("Salsa", ["salsa"]),
    ("Prepared Produce", ["garlic & herb", "ginger & lemongrass", "jalapeno lime", "onion", "original"]),
    ("Cocktail Bitters", ["bitters"]),
]


def derive_category(product_name: str) -> str:
    name_lower = product_name.lower()
    for category, keywords in CATEGORY_RULES:
        if any(kw in name_lower for kw in keywords):
            return category
    return "Other"


def slugify(*parts: str) -> str:
    text = "-".join(parts).upper()
    text = re.sub(r"[^A-Z0-9]+", "-", text).strip("-")
    return text[:60]


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen_skus = set()
    rows_written = 0
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "name", "brand", "category", "description", "source_url", "data_source"])
        for brand, name, url in PRODUCTS:
            sku = "KEHE-" + slugify(brand, name)
            # de-dupe in the unlikely case two products slugify identically
            base_sku, n = sku, 2
            while sku in seen_skus:
                sku = f"{base_sku}-{n}"
                n += 1
            seen_skus.add(sku)

            category = derive_category(name)
            description = (
                f"{brand} product, sourced from KeHE's public retailers/brand-partner page. "
                f"No baseline sales or sales history is available for this item yet."
            )
            writer.writerow([sku, name, brand, category, description, url, "kehe_public_marketing_page"])
            rows_written += 1

    print(f"Wrote {rows_written} products to {OUT_PATH}")


if __name__ == "__main__":
    main()
