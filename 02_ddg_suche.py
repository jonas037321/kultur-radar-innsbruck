"""
Aufgabe 3 – DuckDuckGo-Suche mit Parameter-Übergabe
===================================================
Playwright öffnet duckduckgo.com, tippt den Suchbegriff automatisch ins Suchfeld,
wartet auf die Ergebnisseite, macht einen Screenshot und speichert die Treffer
(Titel, Link, Snippet) als CSV.

    python 02_ddg_suche.py "Playwright Python Tutorial"
    python 02_ddg_suche.py "Neil Cowley Trio" --anzahl 5

Reale Anwendung – "Reinhören bevor man hingeht":
    python 02_ddg_suche.py --kultur-radar 10

liest data/treibhaus_events.csv (von 01_treibhaus.py), sucht für die nächsten
N Konzerte nach dem Künstler und sammelt automatisch die Hör-/Video-Links
(YouTube, Spotify, Bandcamp, SoundCloud, eigene Website) -> data/kultur_radar.csv

Hinweis: DuckDuckGo liefert Headless-Browsern eine Fehlerseite (HTTP 418),
deshalb läuft der Browser hier sichtbar (PLAYWRIGHT_HEADLESS=False in der .env).
"""
import argparse
import re
from urllib.parse import urlparse

import pandas as pd
from playwright.sync_api import Page, sync_playwright

from config import DATA_DIR, HEADLESS, SCREENSHOT_DIR

HOER_PLATTFORMEN = {
    "youtube.com": "YouTube", "youtu.be": "YouTube", "spotify.com": "Spotify",
    "bandcamp.com": "Bandcamp", "soundcloud.com": "SoundCloud",
    "music.apple.com": "Apple Music", "instagram.com": "Instagram",
}
IGNORIEREN = ("treibhaus.at", "wikipedia.org", "facebook.com", "oeticket", "eventim")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def suche(page: Page, begriff: str, anzahl: int = 10, screenshot: bool = True) -> pd.DataFrame:
    page.goto("https://duckduckgo.com", wait_until="networkidle")

    # Suchfeld: im Quelltext ein <textarea name="q"> (früher <input name="q">)
    feld = page.locator('[name="q"]:visible')
    feld.fill(begriff)
    feld.press("Enter")

    # Warten bis die Ergebnisse da sind
    page.wait_for_selector('article[data-testid="result"]', timeout=20000)

    if screenshot:
        datei = SCREENSHOT_DIR / f"ddg_{slug(begriff)}.png"
        page.screenshot(path=datei, full_page=False)
        print(f"Screenshot -> {datei}")

    zeilen = []
    for rang, art in enumerate(page.locator('article[data-testid="result"]').all()[:anzahl], start=1):
        titel = art.locator('a[data-testid="result-title-a"]')
        snippet = art.locator('[data-result="snippet"]')
        link = titel.get_attribute("href")
        zeilen.append({
            "suchbegriff": begriff,
            "rang": rang,
            "titel": titel.inner_text().strip(),
            "link": link,
            "domain": urlparse(link).netloc.removeprefix("www."),
            "snippet": snippet.first.inner_text().strip() if snippet.count() else "",
        })
    return pd.DataFrame(zeilen)


def kuenstler_aus_titel(titel: str) -> str:
    """'NEIL COWLEY TRIO: ENTITY - EINE REUNION // POST JAZZ' -> 'NEIL COWLEY TRIO'"""
    return re.split(r"\s*(?::|//| - )\s*", titel)[0].strip()


def kultur_radar(page: Page, n: int) -> pd.DataFrame:
    events = pd.read_csv(DATA_DIR / "treibhaus_events.csv")
    konzerte = events[events["kategorie"] == "Konzert"].head(n)
    ergebnis = []
    for _, ev in konzerte.iterrows():
        kuenstler = kuenstler_aus_titel(ev["titel"])
        print(f"  suche: {kuenstler}")
        treffer = suche(page, f"{kuenstler} music", anzahl=10, screenshot=False)
        links = {}
        for _, t in treffer.iterrows():
            if any(i in t["domain"] for i in IGNORIEREN):
                continue
            plattform = next((name for dom, name in HOER_PLATTFORMEN.items() if dom in t["domain"]), None)
            if plattform and plattform not in links:
                links[plattform] = t["link"]
            elif not plattform and "Website" not in links:
                links["Website"] = t["link"]   # erster sonstiger Treffer = wahrscheinlich offizielle Seite
        ergebnis.append({"datum": ev["datum"], "beginn": ev["beginn"], "kuenstler": kuenstler,
                         "event": ev["link"], **links})
        page.wait_for_timeout(1500)  # höflich bleiben, nicht im Sekundentakt suchen
    return pd.DataFrame(ergebnis)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suchbegriff", nargs="?", help="Was gesucht werden soll")
    ap.add_argument("--anzahl", type=int, default=10, help="max. Anzahl Treffer (Standard 10)")
    ap.add_argument("--kultur-radar", type=int, metavar="N",
                    help="Hör-Links für die nächsten N Treibhaus-Konzerte suchen")
    args = ap.parse_args()
    if not args.suchbegriff and not args.kultur_radar:
        ap.error("Suchbegriff oder --kultur-radar N angeben")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(locale="de-AT")

        if args.suchbegriff:
            df = suche(page, args.suchbegriff, args.anzahl)
            datei = DATA_DIR / f"ddg_{slug(args.suchbegriff)}.csv"
            df.to_csv(datei, index=False, encoding="utf-8-sig")
            print(df[["rang", "domain", "titel"]].to_string(index=False))
            print(f"-> {datei}")

        if args.kultur_radar:
            df = kultur_radar(page, args.kultur_radar)
            df.to_csv(DATA_DIR / "kultur_radar.csv", index=False, encoding="utf-8-sig")
            spalten = [c for c in ["datum", "kuenstler", "YouTube", "Spotify", "Bandcamp"] if c in df]
            print(df[spalten].to_string(index=False))
            print(f"-> {DATA_DIR / 'kultur_radar.csv'}")

        browser.close()


if __name__ == "__main__":
    main()
