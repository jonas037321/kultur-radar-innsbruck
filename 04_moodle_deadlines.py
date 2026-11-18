"""
Aufgabe 3.1 – Daten aus einem Login-geschützten Bereich: Moodle
===============================================================
Erweiterung des Moodle-Beispiels: Nicht nur die Kurse holen, sondern
**alle anstehenden Abgaben/Termine** – als CSV und als Kalender-Datei (.ics).
Nie wieder eine Abgabe verpassen: die .ics einfach ins Handy importieren.

Ablauf:
  1. Playwright öffnet die Moodle-Login-Seite und befüllt Benutzername/Passwort
     automatisch aus der .env (keine Benutzerinteraktion nötig)
  2. Nach dem Login wird der Session-Key (M.cfg.sesskey) aus der Seite gelesen
  3. Über die gleiche AJAX-Schnittstelle, die auch der Moodle-"Zeitleiste"-Block
     verwendet, werden Kurse und Termine als JSON geholt (stabiler als HTML parsen)
  4. Pandas -> data/moodle_kurse.csv, data/moodle_deadlines.csv, data/moodle_deadlines.ics

.env:
    MOODLE_URL=https://moodle.meine-schule.at
    MOODLE_USER=...
    MOODLE_PASSWORD=...

    python 04_moodle_deadlines.py --tage 30
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
from playwright.sync_api import sync_playwright

from config import DATA_DIR, HEADLESS


def ajax(page, base: str, sesskey: str, methode: str, args: dict):
    """Ruft eine Moodle-Webservice-Funktion mit der Login-Session des Browsers auf."""
    antwort = page.request.post(
        f"{base}/lib/ajax/service.php?sesskey={sesskey}&info={methode}",
        data=[{"index": 0, "methodname": methode, "args": args}],
    ).json()[0]
    if antwort.get("error"):
        raise RuntimeError(f"{methode}: {antwort['exception']['message']}")
    return antwort["data"]


def ics(df: pd.DataFrame, pfad) -> None:
    esc = lambda s: str(s).replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,")
    jetzt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    z = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//kultur-radar//moodle//DE", "X-WR-CALNAME:Moodle Abgaben"]
    for _, r in df.iterrows():
        t = datetime.fromtimestamp(r["timestamp"], timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        z += ["BEGIN:VEVENT", f"UID:moodle-{r['id']}", f"DTSTAMP:{jetzt}", f"DTSTART:{t}", f"DTEND:{t}",
              f"SUMMARY:{esc(r['kurs'])}: {esc(r['name'])}", f"URL:{r['url']}",
              "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:Abgabe morgen!", "END:VALARM",
              "END:VEVENT"]
    z.append("END:VCALENDAR")
    pfad.write_text("\r\n".join(z), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tage", type=int, default=60, help="wie viele Tage in die Zukunft (Standard 60)")
    args = ap.parse_args()

    base = os.getenv("MOODLE_URL", "").rstrip("/")
    user, pw = os.getenv("MOODLE_USER"), os.getenv("MOODLE_PASSWORD")
    if not (base and user and pw):
        sys.exit("Bitte MOODLE_URL, MOODLE_USER und MOODLE_PASSWORD in der .env setzen (siehe .env.example)")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.goto(f"{base}/login/index.php")

        # Eingabefelder automatisch befüllen (Standard-IDs des Moodle-Login-Formulars)
        page.fill("#username", user)
        page.fill("#password", pw)
        page.click("#loginbtn")
        page.wait_for_load_state("networkidle")
        if "login" in page.url:
            sys.exit("Login fehlgeschlagen – Zugangsdaten in der .env prüfen")

        sesskey = page.evaluate("() => M.cfg.sesskey")
        print("Eingeloggt als", page.locator(".usertext, .userbutton .usertext").first.inner_text()
              if page.locator(".usertext").count() else user)

        kurse = ajax(page, base, sesskey, "core_course_get_enrolled_courses_by_timeline_classification",
                     {"offset": 0, "limit": 0, "classification": "inprogress", "sort": "fullname"})["courses"]
        df_kurse = pd.DataFrame([{"id": k["id"], "kurs": k["fullname"], "kurzname": k["shortname"],
                                  "fortschritt_prozent": k.get("progress"), "url": k["viewurl"]} for k in kurse])
        df_kurse.to_csv(DATA_DIR / "moodle_kurse.csv", index=False, encoding="utf-8-sig")
        print(f"{len(df_kurse)} Kurse -> data/moodle_kurse.csv")

        jetzt = int(time.time())
        events = ajax(page, base, sesskey, "core_calendar_get_action_events_by_timesort",
                      {"timesortfrom": jetzt, "timesortto": jetzt + args.tage * 86400,
                       "limitnum": 50, "limittononsuspendedevents": True})["events"]
        browser.close()

    df = pd.DataFrame([{
        "id": e["id"],
        "faellig": datetime.fromtimestamp(e["timesort"]).strftime("%Y-%m-%d %H:%M"),
        "timestamp": e["timesort"],
        "kurs": e["course"]["fullname"],
        "name": e["activityname"] or e["name"],
        "typ": e["modulename"],
        "erledigt": not e.get("action", {}).get("actionable", True) if e.get("action") else None,
        "url": e["url"],
    } for e in events])
    if df.empty:
        print(f"Keine Termine in den nächsten {args.tage} Tagen 🎉")
        return
    df["tage_bis_faellig"] = ((df["timestamp"] - jetzt) / 86400).round(1)
    df.to_csv(DATA_DIR / "moodle_deadlines.csv", index=False, encoding="utf-8-sig")
    ics(df, DATA_DIR / "moodle_deadlines.ics")
    print(df[["faellig", "tage_bis_faellig", "kurs", "name"]].to_string(index=False))
    print("-> data/moodle_deadlines.csv, data/moodle_deadlines.ics")


if __name__ == "__main__":
    main()
