"""
Aufgabe 4 – KI-gesteuerte Automatisierung mit browser-use + Vergleich mit Playwright
===================================================================================
Gleiche Aufgabe, zwei Ansätze:
  * Playwright:  Selektoren selbst gesucht ->       article.product_pod, p.price_color
  * browser-use: Aufgabe in natürlicher Sprache -> LLM entscheidet, was es tut

Aufgabe: "Titel, Preis und Sterne der ersten 20 Bücher auf books.toscrape.com"
Gemessen wird: Laufzeit, Schritte, Tokens, Kosten, Vollständigkeit, Korrektheit
(Korrektheit = Vergleich mit dem Playwright-Ergebnis als "Ground Truth").

    python 05_browser_use_vergleich.py                              # nur Ollama-Modelle
    python 05_browser_use_vergleich.py --modelle ollama:gpt-oss:20b anthropic:claude-sonnet-5-5

Modell-Angaben:
    ollama:<modell>          lokal über Ollama (kein Key)
    anthropic:<modell>       braucht ANTHROPIC_API_KEY in der .env
    openai:<modell>          braucht OPENAI_API_KEY
    google:<modell>          braucht GOOGLE_API_KEY

ACHTUNG: browser-use 1.0 hat eine andere API als im Übungsblatt (0.x):
ChatOllama gibt es nicht mehr -> ChatOpenAI(model, base_url=".../v1", api_key="ollama")
"""
import argparse
import asyncio
import os
import time

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")   # keine Telemetrie an browser-use senden

import pandas as pd
from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from config import DATA_DIR, HEADLESS

URL = "https://books.toscrape.com"
ANZAHL = 20
TASK = (f"Go to {URL} and extract the title, the price (number only, without £) and the star rating "
        f"(1-5 as integer) of the first {ANZAHL} books on the first page. Use the full title from the "
        "link's title attribute, not the truncated text. Return all of them.")


class Book(BaseModel):
    title: str
    price: float
    stars: int


class Books(BaseModel):
    books: list[Book]


# ---------------------------------------------------------------- Playwright
def playwright_loesung() -> tuple[pd.DataFrame, dict]:
    sterne = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
    t0 = time.perf_counter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.goto(URL)
        zeilen = [{
            "title": b.locator("h3 a").get_attribute("title"),
            "price": float(b.locator("p.price_color").inner_text().lstrip("£Â")),
            "stars": sterne[b.locator("p.star-rating").get_attribute("class").split()[-1]],
        } for b in page.locator("article.product_pod").all()[:ANZAHL]]
        browser.close()
    dauer = time.perf_counter() - t0
    return pd.DataFrame(zeilen), {"ansatz": "Playwright", "modell": "-", "laufzeit_s": round(dauer, 1),
                                  "schritte": 1, "tokens_input": 0, "tokens_output": 0, "kosten_usd": 0.0}


# ---------------------------------------------------------------- browser-use
def llm_fuer(spec: str):
    from browser_use import ChatOpenAI
    anbieter, modell = spec.split(":", 1)
    if anbieter == "ollama":
        return ChatOpenAI(modell, base_url=os.getenv("OLLAMA_URL", "http://localhost:11434/v1"), api_key="ollama")
    return f"{anbieter}:{modell}"   # browser-use 1.0 akzeptiert Pydantic-AI-Modellstrings


async def browser_use_loesung(spec: str) -> tuple[pd.DataFrame, dict]:
    from browser_use import Agent, Browser
    agent = Agent(task=TASK, llm=llm_fuer(spec), output_model_schema=Books,
                  # Browser() ohne Argument wäre in 1.0 ein CLOUD-Browser -> lokales Chromium erzwingen
                  browser=Browser("chromium", headless=HEADLESS), judge=False)
    t0 = time.perf_counter()
    info = {"ansatz": "browser-use", "modell": spec}
    try:
        result = await asyncio.wait_for(agent.run(max_steps=25), timeout=900)
        dauer = time.perf_counter() - t0
        out = result.structured_output
        if isinstance(out, str) or out is None:
            out = Books.model_validate_json(result.final_result() or '{"books": []}')
        df = pd.DataFrame([b.model_dump() for b in out.books])
        usage = getattr(result, "usage", {}) or {}
        info |= {"laufzeit_s": round(dauer, 1), "schritte": result.number_of_steps(),
                 "tokens_input": usage.get("input", 0), "tokens_output": usage.get("output", 0),
                 "kosten_usd": getattr(result, "cost_usd", None) or 0.0}
    except Exception as e:   # kleine Modelle scheitern gerne -> trotzdem in die Tabelle
        df = pd.DataFrame(columns=["title", "price", "stars"])
        info |= {"laufzeit_s": round(time.perf_counter() - t0, 1), "fehler": f"{type(e).__name__}: {e}"[:200]}
    return df, info


# ---------------------------------------------------------------- Bewertung
def bewerten(df: pd.DataFrame, wahr: pd.DataFrame) -> dict:
    """Vollständigkeit = wie viele der 20 Titel gefunden; Korrektheit = davon Preis+Sterne richtig."""
    if df.empty:
        return {"gefunden": 0, "vollstaendigkeit_%": 0.0, "korrekt": 0, "korrektheit_%": 0.0}
    m = wahr.merge(df.drop_duplicates("title"), on="title", how="inner", suffixes=("", "_ki"))
    korrekt = ((m["price"] - m["price_ki"]).abs() < 0.01) & (m["stars"] == m["stars_ki"])
    return {"gefunden": len(m), "vollstaendigkeit_%": round(100 * len(m) / len(wahr), 1),
            "korrekt": int(korrekt.sum()), "korrektheit_%": round(100 * korrekt.sum() / len(wahr), 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelle", nargs="+", default=["ollama:gpt-oss:20b", "ollama:llama3.1:8b"])
    args = ap.parse_args()

    wahr, info = playwright_loesung()
    wahr.to_csv(DATA_DIR / "books_playwright.csv", index=False, encoding="utf-8-sig")
    zeilen = [info | bewerten(wahr, wahr)]
    print(f"Playwright: {len(wahr)} Bücher in {info['laufzeit_s']}s")

    for spec in args.modelle:
        print(f"\nbrowser-use mit {spec} ...")
        df, info = asyncio.run(browser_use_loesung(spec))
        df.to_csv(DATA_DIR / f"books_browser_use_{spec.replace(':', '_')}.csv", index=False, encoding="utf-8-sig")
        zeilen.append(info | bewerten(df, wahr))
        print({k: v for k, v in zeilen[-1].items()})

    vergleich = pd.DataFrame(zeilen)
    vergleich.to_csv(DATA_DIR / "vergleich_playwright_browser_use.csv", index=False, encoding="utf-8-sig")
    print("\n" + vergleich.drop(columns=[c for c in ["fehler"] if c in vergleich]).to_string(index=False))


if __name__ == "__main__":
    main()
