"""
Aufgabe 3.1 (eigene Quelle) – Kompletter Buchbestand von books.toscrape.com
==========================================================================
Playwright klickt sich durch alle 50 Katalogseiten ("next"-Button) und holt
alle 1000 Bücher: Titel, Preis, Bewertung (1-5 Sterne), Lagerstatus, Link.
Die Kategorie kommt aus der Seitenleiste (je Kategorie eine eigene Liste).

Auswertung ("Preis-Monitor"):
  * data/books.csv                  – gesamter Bestand
  * data/books_schnaeppchen.csv     – 5-Sterne-Bücher unter 20 £
  * data/books_kategorien.csv       – Anzahl / Ø-Preis / Ø-Bewertung je Kategorie
  * plots/books_preis_vs_rating.png – lohnt sich ein teures Buch?

    python 03_books_katalog.py
"""
import time
from urllib.parse import urljoin

import matplotlib.pyplot as plt
import pandas as pd
from playwright.sync_api import sync_playwright

from config import BASE_DIR, DATA_DIR, HEADLESS

BASE = "https://books.toscrape.com/"
STERNE = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
PLOT_DIR = BASE_DIR / "plots"
PLOT_DIR.mkdir(exist_ok=True)


def buecher_auf_seite(page, kategorie: str) -> list[dict]:
    zeilen = []
    for b in page.locator("article.product_pod").all():
        a = b.locator("h3 a")
        sterne = b.locator("p.star-rating").get_attribute("class").split()[-1]
        zeilen.append({
            "titel": a.get_attribute("title"),
            "kategorie": kategorie,
            "preis_gbp": float(b.locator("p.price_color").inner_text().lstrip("£Â")),
            "sterne": STERNE[sterne],
            "lagernd": "In stock" in b.locator("p.availability").inner_text(),
            "link": urljoin(page.url, a.get_attribute("href")),
        })
    return zeilen


def scrape() -> pd.DataFrame:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.goto(BASE)

        # Alle Kategorien aus der Seitenleiste
        kats = page.locator("div.side_categories ul li ul li a")
        kategorien = [(k.inner_text().strip(), BASE + k.get_attribute("href")) for k in kats.all()]
        print(f"{len(kategorien)} Kategorien")

        alle = []
        for name, url in kategorien:
            page.goto(url)
            while True:
                alle += buecher_auf_seite(page, name)
                weiter = page.locator("li.next a")
                if weiter.count() == 0:
                    break
                weiter.click()          # Pagination wie ein Mensch: auf "next" klicken
                page.wait_for_load_state()
            print(f"  {name:<20} {len(alle):>4} Bücher gesamt")
        browser.close()
    return pd.DataFrame(alle)


def main():
    t0 = time.perf_counter()
    df = scrape()
    print(f"\n{len(df)} Bücher in {time.perf_counter() - t0:.1f}s geholt")
    df.to_csv(DATA_DIR / "books.csv", index=False, encoding="utf-8-sig")

    schnaeppchen = df[(df["sterne"] == 5) & (df["preis_gbp"] < 20)].sort_values("preis_gbp")
    schnaeppchen.to_csv(DATA_DIR / "books_schnaeppchen.csv", index=False, encoding="utf-8-sig")
    print(f"\n{len(schnaeppchen)} Schnäppchen (5 Sterne, < 20 £), die günstigsten:")
    print(schnaeppchen[["preis_gbp", "kategorie", "titel"]].head(8).to_string(index=False))

    kat = (df.groupby("kategorie")
             .agg(anzahl=("titel", "size"), preis_mittel=("preis_gbp", "mean"), sterne_mittel=("sterne", "mean"))
             .round(2).sort_values("anzahl", ascending=False))
    kat.to_csv(DATA_DIR / "books_kategorien.csv", encoding="utf-8-sig")
    print("\nTop-Kategorien:\n" + kat.head(8).to_string())

    korr = df["preis_gbp"].corr(df["sterne"])
    print(f"\nKorrelation Preis <-> Sterne: {korr:.3f}")

    fig, ax = plt.subplots(figsize=(8, 5))
    df.boxplot(column="preis_gbp", by="sterne", ax=ax, grid=False)
    ax.set_title(f"Preis je Bewertung (Korrelation r = {korr:.2f})")
    fig.suptitle("")
    ax.set_xlabel("Sterne")
    ax.set_ylabel("Preis in £")
    fig.tight_layout()
    fig.savefig(PLOT_DIR / "books_preis_vs_rating.png", dpi=120)
    print(f"-> {PLOT_DIR / 'books_preis_vs_rating.png'}")


if __name__ == "__main__":
    main()
