from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from . import config
from .extract import CricketAPIClient, load_sample, save_raw
from .load import load_all
from .logger import get_logger
from .schemas import validate_matches, validate_series
from .transform import build_tables, quality_report

log = get_logger()


def run_etl(offline: bool = False, max_pages: int = config.MAX_PAGES) -> dict:
    config.ensure_dirs()
    started = datetime.now()
    log.info("=" * 60)
    log.info("ETL started (%s)", "OFFLINE sample" if offline else "LIVE API")

    if offline:
        raw_matches = load_sample("matches_sample.json")
        raw_series = load_sample("series_sample.json")
        source = "synthetic_sample"
    else:
        client = CricketAPIClient()
        raw_matches = client.fetch_matches(max_pages)
        raw_series = client.fetch_series(max_pages=3)
        save_raw(raw_matches, "matches")
        save_raw(raw_series, "series")
        source = "cricketdata.org"
    log.info("EXTRACT  : %d match records, %d series records", len(raw_matches), len(raw_series))

    valid_matches, rejected_matches = validate_matches(raw_matches)
    valid_series, rejected_series = validate_series(raw_series)
    rejected = rejected_matches + rejected_series
    log.info("VALIDATE : %d valid, %d rejected", len(valid_matches), len(rejected))
    if not valid_matches:
        raise RuntimeError("No valid match records - nothing to load.")

    result = build_tables(valid_matches, valid_series)

    pd.DataFrame(rejected).to_csv(config.PROCESSED_DIR / "rejected_records.csv", index=False)
    result.matches.to_csv(config.PROCESSED_DIR / "matches_clean.csv", index=False)
    result.innings.to_csv(config.PROCESSED_DIR / "innings_clean.csv", index=False)
    report = quality_report(result, rejected, extracted=len(raw_matches))
    (config.REPORT_DIR / "data_quality_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    counts = load_all(result, source, len(raw_matches), len(rejected), started)
    log.info("ETL finished in %.1fs", (datetime.now() - started).total_seconds())
    return {"quality": report, "loaded": counts}