from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

ROOT_DIR = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(ROOT_DIR / ".env")

API_KEY: str = os.getenv("CRICKET_API_KEY", "")
BASE_URL: str = "https://api.cricapi.com/v1"
PAGE_SIZE: int = 25       
MAX_PAGES: int = int(os.getenv("MAX_PAGES", "20"))
REQUEST_TIMEOUT: int = 20       

DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLE_DIR = DATA_DIR / "sample"
REPORT_DIR = ROOT_DIR / "reports"
FIG_DIR = REPORT_DIR / "figures"
LOG_DIR = ROOT_DIR / "logs"
DB_PATH = DATA_DIR / "cricket.db"

FORMATS = ("Test", "ODI", "T20")
LIMITED_OVERS = ("ODI", "T20")
MAX_WICKETS = 10
FIRST_CRICKET_YEAR = 2000    


def ensure_dirs() -> None:
    """Create every output folder if it does not exist yet."""
    for folder in (RAW_DIR, PROCESSED_DIR, SAMPLE_DIR, FIG_DIR, LOG_DIR):
        folder.mkdir(parents=True, exist_ok=True)
