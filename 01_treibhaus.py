"""
Aufgabe 2 – Veranstaltungen vom Treibhaus Innsbruck holen
=========================================================
Playwright öffnet https://treibhaus.at/programm, liest alle Veranstaltungen
(Datum, Beginnzeit, Titel, Beschreibung, Link, Ticket-Link) aus und speichert sie

  * als CSV            -> data/treibhaus_events.csv
  * als Kalender-Datei -> data/treibhaus.ics   (in Google/Outlook/Apple-Kalender importierbar)

Zusätzlich wird jede Veranstaltung grob kategorisiert (Konzert, Lesung, ...)
und mit --interessen kann man sich nur die Events holen, die einen interessieren:

    python 01_treibhaus.py
    python 01_treibhaus.py --interessen jazz,blues,kabarett
"""
import argparse
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from playwright.sync_api import sync_playwright

from config import DATA_DIR, HEADLESS

URL = "https://treibhaus.at/programm"

# Einfache Stichwort-Kategorisierung (Reihenfolge = Priorität)
KATEGORIEN = {
    "Kinder": ["kinder", "familie", "puppen", "kids"],
    "Lesung": ["lesung", "liest", "buch", "roman", "literatur", "poetry"],
    "Kabarett/Theater": ["kabarett", "theater", "comedy", "satire", "bühne", "impro"],
    "Film": ["film", "kino", "doku"],
    "Diskussion": ["diskussion", "gespräch", "vortrag", "podium", "talk", "minister"],
    "Party/DJ": ["dj", "party", "clubbing", "tanz", "disco"],
    "Konzert": ["konzert", "band", "album", "jazz", "rock", "folk", "blues", "pop",
                "trio", "quartett", "quintett", "orchester", "gitarre", "stimme",
                "song", "musik", "tour", "release", "funk", "soul", "punk", "kora"],
}


def kategorie(text: str) -> str:
    t = text.lower()
    for kat, woerter in KATEGORIEN.items():
        if any(re.search(rf"\b{re.escape(w)}", t) for w in woerter):
            return kat
    return "Sonstiges"


def scrape() -> pd.DataFrame:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle")

        # Jede Veranstaltung ist ein <div itemprop="event"> (schema.org/Event)
        events = page.locator('div[itemprop="event"]')
        print(f"{events.count()} Veranstaltungen gefunden")

        zeilen = []
        for ev in events.all():
            start = ev.locator('div.event-date span[itemprop="startDate"]')
            beginn = datetime.fromisoformat(start.get_attribute("content"))
            ticket = ev.locator('a[itemprop="offers"]')
            beschreibung = ev.locator("div.share-sub")
            titel = ev.locator('span[itemprop="name"]').inner_text().strip()
            text = beschreibung.inner_text().strip() if beschreibung.count() else ""
            zeilen.append({
                "datum": beginn.date().isoformat(),
                "wochentag": beginn.strftime("%a"),
                "beginn": beginn.strftime("%H:%M"),
                "titel": titel,
                "beschreibung": text,
                "kategorie": kategorie(f"{titel} {text}"),
                "eintritt_frei": bool(re.search(r"eintritt\s*(frei|gratis)|freier eintritt", text, re.I)),
                "link": ev.locator('a[itemprop="url"]').get_attribute("href"),
                "tickets": ticket.get_attribute("href") if ticket.count() else None,
            })
        browser.close()
    return pd.DataFrame(zeilen)


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def als_ics(df: pd.DataFrame, pfad) -> None:
    """Schreibt die Events als iCalendar-Datei (RFC 5545)."""
    jetzt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zeilen = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//kultur-radar//treibhaus//DE",
              "X-WR-CALNAME:Treibhaus Innsbruck", "X-WR-TIMEZONE:Europe/Vienna"]
    for _, r in df.iterrows():
        start = datetime.fromisoformat(f"{r['datum']}T{r['beginn']}")
        ende = start + timedelta(hours=2, minutes=30)  # Dauer ist nicht angegeben -> Schätzung
        uid = r["link"].rstrip("/").split("/")[-1]
        zeilen += [
            "BEGIN:VEVENT",
            f"UID:{uid}@treibhaus.at",
            f"DTSTAMP:{jetzt}",
            f"DTSTART;TZID=Europe/Vienna:{start:%Y%m%dT%H%M%S}",
            f"DTEND;TZID=Europe/Vienna:{ende:%Y%m%dT%H%M%S}",
            f"SUMMARY:{ics_escape(r['titel'])}",
            f"DESCRIPTION:{ics_escape(r['beschreibung'] + chr(10) + r['link'])}",
            "LOCATION:Treibhaus\\, Angerzellgasse 8\\, 6020 Innsbruck",
            f"URL:{r['link']}",
            f"CATEGORIES:{r['kategorie']}",
            "END:VEVENT",
        ]
    zeilen.append("END:VCALENDAR")
    pfad.write_text("\r\n".join(zeilen), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interessen", help="Kommagetrennte Stichwörter, z.B. jazz,kabarett")
    args = ap.parse_args()

    df = scrape()
    df.to_csv(DATA_DIR / "treibhaus_events.csv", index=False, encoding="utf-8-sig")
    als_ics(df, DATA_DIR / "treibhaus.ics")
    print(f"-> {DATA_DIR / 'treibhaus_events.csv'}\n-> {DATA_DIR / 'treibhaus.ics'}")

    print("\nVeranstaltungen pro Kategorie:")
    print(df["kategorie"].value_counts().to_string())

    if args.interessen:
        woerter = [w.strip() for w in args.interessen.split(",") if w.strip()]
        muster = "|".join(map(re.escape, woerter))
        treffer = df[(df["titel"] + " " + df["beschreibung"]).str.contains(muster, case=False)]
        treffer.to_csv(DATA_DIR / "treibhaus_meine_events.csv", index=False, encoding="utf-8-sig")
        als_ics(treffer, DATA_DIR / "treibhaus_meine_events.ics")
        print(f"\n{len(treffer)} Events passen zu {woerter}:")
        print(treffer[["datum", "beginn", "titel"]].to_string(index=False))


if __name__ == "__main__":
    main()
