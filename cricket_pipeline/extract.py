from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config
from .logger import get_logger

log = get_logger()


class CricketAPIError(RuntimeError):
    """Raised for any problem while talking to the cricket API."""

class CricketAPIClient:
    """Small, well-behaved client: retries, timeouts, pagination and safe errors."""

    def __init__(self, api_key: str = config.API_KEY, base_url: str = config.BASE_URL):
        if not api_key:
            raise CricketAPIError(
                "CRICKET_API_KEY is missing. Copy .env.example to .env and add your key "
                "(free at https://cricketdata.org), or run with --offline."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, endpoint: str, **params) -> dict:
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
    
            raise CricketAPIError(f"Request to '{endpoint}' failed: {type(exc).__name__}") from None
        except ValueError:
            raise CricketAPIError(f"'{endpoint}' did not return valid JSON") from None

        if payload.get("status") != "success":
            raise CricketAPIError(f"API refused '{endpoint}': {payload.get('reason', 'unknown reason')}")
        return payload

    def paginate(self, endpoint: str, max_pages: int = config.MAX_PAGES) -> list[dict]:
        """Walk through ?offset=0,25,50... until the API runs out of rows."""
        records: list[dict] = []
        for page in range(max_pages):
            payload = self._get(endpoint, offset=page * config.PAGE_SIZE)
            rows = payload.get("data") or []
            records.extend(rows)

            info = payload.get("info", {})
            total = info.get("totalRows")
            log.info(
                "%s page %d: +%d rows (total so far %d / %s) | hits today: %s/%s",
                endpoint, page + 1, len(rows), len(records), total,
                info.get("hitsToday", "?"), info.get("hitsLimit", "?"),
            )
            if not rows or (total is not None and len(records) >= total):
                break
            time.sleep(0.3) 
        return records

    def fetch_matches(self, max_pages: int = config.MAX_PAGES) -> list[dict]:
        return self.paginate("matches", max_pages)

    def fetch_series(self, max_pages: int = config.MAX_PAGES) -> list[dict]:
        return self.paginate("series", max_pages)

def save_raw(records: list[dict], name: str) -> Path:
    """Keep an untouched copy of what the API returned (data lineage / audit)."""
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = config.RAW_DIR / f"{name}_{stamp}.json"
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    log.info("Raw snapshot saved -> %s", path.relative_to(config.ROOT_DIR))
    return path


def load_sample(name: str) -> list[dict]:
    """Offline mode: read the bundled SYNTHETIC sample (testing only)."""
    path = config.SAMPLE_DIR / name
    if not path.exists():
        raise CricketAPIError(f"{path} not found. Run: python scripts/generate_sample_data.py")
    log.warning("OFFLINE MODE: using synthetic sample '%s' (not real cricket data!)", name)
    return json.loads(path.read_text(encoding="utf-8"))