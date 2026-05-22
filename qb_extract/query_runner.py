"""
Paged query execution against QuickBooks Desktop.

QB returns large result sets via an iterator pattern: each response includes
an `iteratorID` and `iteratorRemainingCount`, and you keep sending the same
query with `iterator="Continue"` and the prior ID until remaining = 0.

Getting this right once means you never have to think about it again.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path

from qb_qbxml.connection import QBSession, wrap_qbxml

logger = logging.getLogger(__name__)

# Match how many records came back and the iterator state, without parsing the full tree.
# QB sometimes returns response tags in slightly varied casing; we extract from attributes.
ITERATOR_REMAINING_RE = re.compile(r'iteratorRemainingCount="(\d+)"', re.IGNORECASE)
ITERATOR_ID_RE = re.compile(r'iteratorID="([^"]+)"', re.IGNORECASE)
STATUS_CODE_RE = re.compile(r'statusCode="(\d+)"', re.IGNORECASE)
STATUS_MESSAGE_RE = re.compile(r'statusMessage="([^"]*)"', re.IGNORECASE)


class QBQueryError(Exception):
    """Raised when a QB query returns a non-zero statusCode."""


def run_paged_query(
    session: QBSession,
    request_tag: str,
    inner_filters: str = "",
    page_size: int = 100,
    qbxml_version: str = "16.0",
    output_dir: Path | None = None,
    page_prefix: str = "page",
) -> Iterator[str]:
    """
    Execute a QB query with iterator-based paging, yielding each page's raw XML response.

    Args:
        session: An open QBSession.
        request_tag: The query request element name, e.g. 'InvoiceQueryRq'.
        inner_filters: XML fragment for filters that go INSIDE the request element.
            E.g. '<TxnDateRangeFilter><FromTxnDate>2024-01-01</FromTxnDate>...'.
            Iterator and MaxReturned attributes are added automatically.
        page_size: Records per page. 100-200 is a good range. Too large = timeouts.
        qbxml_version: QBXML version for the envelope.
        output_dir: If provided, each page's raw XML is also written here as
            `{page_prefix}_NNN.xml`. Highly recommended.
        page_prefix: Filename prefix for saved pages.

    Yields:
        Raw XML response string for each page.
    """
    iterator_id: str | None = None
    page_num = 0
    total_yielded = 0

    while True:
        page_num += 1

        # Build the request element with iterator attributes
        if iterator_id is None:
            iter_attrs = ' iterator="Start"'
        else:
            iter_attrs = f' iterator="Continue" iteratorID="{iterator_id}"'

        # MaxReturned goes inside the request body
        body = (
            f"<{request_tag}{iter_attrs}>\n"
            f"  <MaxReturned>{page_size}</MaxReturned>\n"
            f"  {inner_filters}\n"
            f"</{request_tag}>"
        )

        request_xml = wrap_qbxml(body, version=qbxml_version)

        logger.info("Querying %s page %d (page_size=%d)", request_tag, page_num, page_size)
        response_xml = session.process_request(request_xml)

        # Parse status to detect errors early
        _check_status(response_xml, request_tag, page_num)

        # Save raw response
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            page_file = output_dir / f"{page_prefix}_{page_num:04d}.xml"
            page_file.write_text(response_xml, encoding="utf-8")
            logger.debug("Saved %s", page_file)

        yield response_xml
        total_yielded += 1

        # Extract iterator state from response attributes
        remaining_match = ITERATOR_REMAINING_RE.search(response_xml)
        id_match = ITERATOR_ID_RE.search(response_xml)

        if not remaining_match:
            # No iterator info = single-page response, we're done
            logger.info("%s: single-page response, complete after %d pages", request_tag, page_num)
            break

        remaining = int(remaining_match.group(1))
        iterator_id = id_match.group(1) if id_match else None

        logger.info("%s page %d done. Remaining: %d", request_tag, page_num, remaining)

        if remaining == 0:
            logger.info("%s: complete after %d pages", request_tag, page_num)
            break

        if iterator_id is None:
            logger.warning("%s: remaining=%d but no iteratorID; stopping", request_tag, remaining)
            break

    logger.info("%s: yielded %d page(s) total", request_tag, total_yielded)


def _check_status(response_xml: str, request_tag: str, page_num: int) -> None:
    """
    Inspect the response status. statusCode '0' = OK, '1' = warning (e.g. no records found),
    anything else = error. Status '1' is fine for empty queries.
    """
    status_match = STATUS_CODE_RE.search(response_xml)
    if not status_match:
        return  # No status found; let the caller deal with it

    code = status_match.group(1)
    if code in ("0", "1"):
        return

    msg_match = STATUS_MESSAGE_RE.search(response_xml)
    message = msg_match.group(1) if msg_match else "(no message)"
    raise QBQueryError(f"{request_tag} page {page_num} returned statusCode={code}: {message}")


def run_simple_query(
    session: QBSession,
    request_tag: str,
    inner_filters: str = "",
    qbxml_version: str = "16.0",
    output_file: Path | None = None,
) -> str:
    """
    Run a single-page query (no iterator). For small entity sets where you know
    the result is small (e.g. CurrencyQueryRq, TermsQueryRq).
    """
    body = f"<{request_tag}>{inner_filters}</{request_tag}>"
    request_xml = wrap_qbxml(body, version=qbxml_version)

    logger.info("Querying %s (single page)", request_tag)
    response_xml = session.process_request(request_xml)
    _check_status(response_xml, request_tag, 1)

    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(response_xml, encoding="utf-8")
        logger.debug("Saved %s", output_file)

    return response_xml
