from __future__ import annotations

import argparse
import sys

from cricket_pipeline import config
from cricket_pipeline.eda import run_eda
from cricket_pipeline.extract import CricketAPIError
from cricket_pipeline.logger import get_logger
from cricket_pipeline.pipeline import run_etl

log = get_logger()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cricket ETL + EDA pipeline")
    parser.add_argument("command", choices=["etl", "eda", "all"])
    parser.add_argument("--offline", action="store_true", help="use the bundled synthetic sample")
    parser.add_argument("--max-pages", type=int, default=config.MAX_PAGES,
                        help="API pages to download (25 matches/page, 1 hit/page)")
    args = parser.parse_args()

    try:
        if args.command in ("etl", "all"):
            run_etl(offline=args.offline, max_pages=args.max_pages)
        if args.command in ("eda", "all"):
            run_eda()
    except CricketAPIError as exc:
        log.error("API problem: %s", exc)
        return 1
    except Exception as exc:
        log.exception("Pipeline failed: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())