"""Generate AI monitoring daily reports for scheduled backend jobs.

Example:
    python scripts/daily_report.py --date 2026-07-10 --format both
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.services.daily_report import DailyReportService


def _parse_date(date_text: str | None):
    if not date_text:
        return None
    return datetime.strptime(date_text, "%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate AI study-room monitoring daily report.")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="both",
        help="Which report artifact to generate.",
    )
    parser.add_argument("--report-dir", help="Output directory. Defaults to backend/reports.")
    parser.add_argument(
        "--disable-llm",
        action="store_true",
        help="Use rule-based recommendations even when LLM credentials are configured.",
    )
    args = parser.parse_args(argv)

    if args.disable_llm:
        Config.LLM_ENABLED = False

    formats = ("json", "markdown") if args.format == "both" else (args.format,)
    service = DailyReportService(report_dir=args.report_dir)
    result = service.generate_artifacts(_parse_date(args.date), formats=formats)

    print(f"DAILY REPORT GENERATED date={result['date']}")
    for kind, path in result["outputs"].items():
        print(f"{kind}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
