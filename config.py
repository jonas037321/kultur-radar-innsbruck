"""Gemeinsame Einstellungen für alle Skripte (werden aus der .env gelesen)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
DATA_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)

# DuckDuckGo blockt Headless-Browser (HTTP 418) -> standardmäßig sichtbar starten
HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "False").lower() in ("1", "true", "yes")
