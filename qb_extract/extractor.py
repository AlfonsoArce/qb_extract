"""
Top-level extraction orchestrator.

Runs every defined query (master + transactional), saves raw XML, writes a manifest.
Designed to be safely re-runnable: a fresh `--run-name` creates a new timestamped folder.
"""

from __future__ import annotations

import json
import logging
import platform
import socket
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from qb_qbxml.connection import QBConnectionError, QBSession
from .queries import (
    MASTER_QUERIES,
    TRANSACTIONAL_QUERIES,
    QueryDef,
    build_transactional_filters,
)
from .query_runner import QBQueryError, run_paged_query, run_simple_query

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    name: str
    request_tag: str
    pages: int = 0
    status: str = "pending"  # pending, success, failed, skipped
    error: str | None = None
    duration_seconds: float = 0.0
    output_dir: str | None = None


@dataclass
class ExtractionManifest:
    started_at: str
    completed_at: str | None = None
    qb_company_file: str | None = None
    qbxml_version: str = ""
    from_date: str | None = None
    to_date: str | None = None
    host: str = ""
    python_version: str = ""
    platform: str = ""
    queries: list[QueryResult] = field(default_factory=list)
    overall_status: str = "running"  # running, success, partial, failed


class Extractor:
    """Orchestrates a full QB data extraction run."""

    def __init__(
        self,
        output_root: Path,
        app_name: str = "QB Data Extractor",
        company_file: str = "",
        qbxml_version: str = "16.0",
        from_date: str | None = None,
        to_date: str | None = None,
        run_name: str | None = None,
    ):
        self.output_root = Path(output_root)
        self.app_name = app_name
        self.company_file = company_file
        self.qbxml_version = qbxml_version
        self.from_date = from_date
        self.to_date = to_date

        if run_name is None:
            run_name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_dir = self.output_root / run_name

        self.manifest = ExtractionManifest(
            started_at=datetime.now(timezone.utc).isoformat(),
            qbxml_version=qbxml_version,
            from_date=from_date,
            to_date=to_date,
            host=socket.gethostname(),
            python_version=sys.version.split()[0],
            platform=platform.platform(),
        )

    def run(
        self,
        skip_master: bool = False,
        skip_transactional: bool = False,
        only: list[str] | None = None,
    ) -> ExtractionManifest:
        """
        Execute the full extraction.

        Args:
            skip_master: Skip master data queries.
            skip_transactional: Skip transactional queries.
            only: If provided, only run queries whose `name` is in this list.

        Returns:
            The completed ExtractionManifest.
        """
        self.run_dir.mkdir(parents=True, exist_ok=True)
        run_log_handler = self._attach_run_log()
        try:
            logger.info("Extraction output: %s", self.run_dir)

            # Write a stub manifest immediately so we have it even if the process dies
            self._write_manifest()

            try:
                with QBSession(
                    app_name=self.app_name,
                    company_file=self.company_file,
                    qbxml_version=self.qbxml_version,
                ) as session:
                    # Capture company file path
                    try:
                        self.manifest.qb_company_file = session.get_company_file_path()
                        logger.info("Connected to company file: %s", self.manifest.qb_company_file)
                    except Exception as e:
                        logger.warning("Could not read company file path: %s", e)

                    # Master queries
                    if not skip_master:
                        for qdef in MASTER_QUERIES:
                            if only and qdef.name not in only:
                                continue
                            self._run_one(session, qdef, is_transactional=False)

                    # Transactional queries
                    if not skip_transactional:
                        for qdef in TRANSACTIONAL_QUERIES:
                            if only and qdef.name not in only:
                                continue
                            self._run_one(session, qdef, is_transactional=True)

            except QBConnectionError as e:
                logger.error("Connection failed: %s", e)
                self.manifest.overall_status = "failed"
                self._write_manifest()
                raise

            # Determine overall status
            failed = [q for q in self.manifest.queries if q.status == "failed"]
            if not failed:
                self.manifest.overall_status = "success"
            elif len(failed) < len(self.manifest.queries):
                self.manifest.overall_status = "partial"
            else:
                self.manifest.overall_status = "failed"

            self.manifest.completed_at = datetime.now(timezone.utc).isoformat()
            self._write_manifest()

            logger.info(
                "Extraction complete: %s (%d queries, %d failed)",
                self.manifest.overall_status,
                len(self.manifest.queries),
                len(failed),
            )
            return self.manifest
        finally:
            self._detach_run_log(run_log_handler)

    def _attach_run_log(self) -> logging.Handler:
        """
        Add a DEBUG-level file handler at run_dir/extraction.log so the run folder
        is self-contained: manifest + raw XML + complete log, independent of the
        process-wide log or the terminal scrollback.
        """
        log_file = self.run_dir / "extraction.log"
        handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logging.getLogger().addHandler(handler)
        logger.info("Per-run log: %s", log_file)
        return handler

    @staticmethod
    def _detach_run_log(handler: logging.Handler) -> None:
        logging.getLogger().removeHandler(handler)
        handler.close()

    def _run_one(self, session: QBSession, qdef: QueryDef, is_transactional: bool) -> None:
        """Execute one query definition and record the outcome."""
        category = "txn" if is_transactional else "master"
        out_dir = self.run_dir / category / qdef.name

        result = QueryResult(
            name=qdef.name,
            request_tag=qdef.request_tag,
            output_dir=str(out_dir.relative_to(self.run_dir)),
        )
        self.manifest.queries.append(result)
        start = time.monotonic()

        try:
            if is_transactional:
                filters = build_transactional_filters(qdef, self.from_date, self.to_date)
            else:
                filters = qdef.inner_filters

            if qdef.supports_iterator:
                pages = 0
                for pages, _ in enumerate(
                    run_paged_query(
                        session=session,
                        request_tag=qdef.request_tag,
                        inner_filters=filters,
                        page_size=qdef.page_size,
                        qbxml_version=self.qbxml_version,
                        output_dir=out_dir,
                        page_prefix="page",
                    ),
                    start=1,
                ):
                    # Update manifest incrementally so crashes preserve progress
                    result.pages = pages
                    self._write_manifest()
            else:
                out_dir.mkdir(parents=True, exist_ok=True)
                run_simple_query(
                    session=session,
                    request_tag=qdef.request_tag,
                    inner_filters=filters,
                    qbxml_version=self.qbxml_version,
                    output_file=out_dir / "page_0001.xml",
                )
                result.pages = 1
                self._write_manifest()

            result.status = "success"

        except QBQueryError as e:
            # Query returned an error status. Some queries (like CurrencyQueryRq
            # when multi-currency is off) will legitimately fail; don't crash the run.
            logger.warning("%s failed (query error): %s", qdef.name, e)
            result.status = "failed"
            result.error = str(e)

        except Exception as e:
            logger.error("%s failed (unexpected): %s\n%s", qdef.name, e, traceback.format_exc())
            result.status = "failed"
            result.error = f"{type(e).__name__}: {e}"

        finally:
            result.duration_seconds = round(time.monotonic() - start, 2)
            self._write_manifest()
            logger.info(
                "%s: %s (%.2fs, %d pages)",
                qdef.name,
                result.status,
                result.duration_seconds,
                result.pages,
            )

    def _write_manifest(self) -> None:
        """Atomically write the manifest to disk."""
        manifest_path = self.run_dir / "manifest.json"
        tmp_path = manifest_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(asdict(self.manifest), f, indent=2, default=str)
        tmp_path.replace(manifest_path)
