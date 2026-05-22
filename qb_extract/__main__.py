"""
Command-line entry point.

Usage examples:
    # Pull everything for last 24 months
    python -m qb_extract --from 2024-05-19 --to 2026-05-19

    # Just master data (no transactions)
    python -m qb_extract --skip-transactional

    # Just invoices for testing
    python -m qb_extract --only invoices --from 2026-01-01

    # A single invoice by its invoice number
    python -m qb_extract --only invoices --ref-number 10523

    # Point at a specific company file (default: currently-open file)
    python -m qb_extract --company-file "C:/QB/MyCompany_DEV.QBW" --from 2024-01-01
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from .extractor import Extractor


def _setup_logging(verbose: bool, log_file: Path) -> None:
    """
    Configure root logging.

    - Root logger at DEBUG so per-handler levels do the filtering.
    - stdout: INFO by default, DEBUG with -v (user-facing verbosity).
    - File handler at log_file: DEBUG always — the on-disk record never depends
      on the terminal scrollback or the -v flag.
    """
    console_level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()  # idempotent across re-invocations in the same process

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(console_level)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qb_extract",
        description="Extract master and transactional data from QuickBooks Desktop.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("./output"),
        help="Root directory for extraction output. A timestamped subfolder is created per run.",
    )
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Optional run folder name. Default: UTC timestamp.",
    )
    parser.add_argument(
        "--app-name",
        type=str,
        default="QB Data Extractor",
        help="App name shown in QB's Integrated Applications. First run requires QB user approval.",
    )
    parser.add_argument(
        "--company-file",
        type=str,
        default="",
        help="Path to .QBW file. Empty = use the currently-open company file.",
    )
    parser.add_argument(
        "--qbxml-version",
        type=str,
        default="16.0",
        help="QBXML spec version. Try 13.0, 14.0, 15.0 if 16.0 fails for older QB versions.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=str,
        default=None,
        help="Transaction date filter (inclusive). Format: YYYY-MM-DD.",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=str,
        default=None,
        help="Transaction end date (inclusive). Format: YYYY-MM-DD. Default: today.",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=None,
        help="Convenience: pull the last N months of transactions (overrides --from).",
    )
    parser.add_argument(
        "--skip-master",
        action="store_true",
        help="Skip master data queries.",
    )
    parser.add_argument(
        "--skip-transactional",
        action="store_true",
        help="Skip transactional queries.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Only run these query names (e.g. --only invoices bills customers).",
    )
    parser.add_argument(
        "--ref-number",
        type=str,
        default=None,
        help=(
            "Pull a single transaction by its exact reference number (e.g. the "
            "invoice number). Ignores the date range. Use with --only to target one "
            "entity, e.g. --only invoices --ref-number 10523."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args(argv)

    # Resolve date range
    from_date = args.from_date
    to_date = args.to_date
    if args.months is not None:
        today = date.today()
        from_date = (today - timedelta(days=30 * args.months)).isoformat()
        to_date = to_date or today.isoformat()

    output_root = args.output_root.resolve()
    log_file = output_root / "extraction.log"
    _setup_logging(args.verbose, log_file)
    logger = logging.getLogger("qb_extract.main")

    logger.info("Starting extraction")
    logger.info("  output_root: %s", output_root)
    logger.info("  company_file: %s", args.company_file or "<currently open>")
    logger.info("  qbxml_version: %s", args.qbxml_version)
    logger.info("  date range: %s -> %s", from_date or "<none>", to_date or "<none>")
    if args.ref_number:
        logger.info("  ref_number: %s (date range ignored)", args.ref_number)
    logger.info("  app_name: %s", args.app_name)

    extractor = Extractor(
        output_root=output_root,
        app_name=args.app_name,
        company_file=args.company_file,
        qbxml_version=args.qbxml_version,
        from_date=from_date,
        to_date=to_date,
        run_name=args.run_name,
        ref_number=args.ref_number,
    )

    try:
        manifest = extractor.run(
            skip_master=args.skip_master,
            skip_transactional=args.skip_transactional,
            only=args.only,
        )
    except Exception as e:
        logger.error("Extraction failed: %s", e)
        return 2

    logger.info("=" * 60)
    logger.info("Run directory: %s", extractor.run_dir)
    logger.info("Overall status: %s", manifest.overall_status)
    logger.info(
        "Queries: %d total, %d failed",
        len(manifest.queries),
        sum(1 for q in manifest.queries if q.status == "failed"),
    )

    return 0 if manifest.overall_status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
