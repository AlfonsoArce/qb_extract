"""
QuickBooks Desktop connection management via QBXMLRP2 COM interface.

The QB Request Processor is single-threaded per company file. Always use the
context manager to ensure sessions are properly closed, otherwise QB will
refuse subsequent connections until the orphaned session is cleaned up.
"""

from __future__ import annotations

import logging
from contextlib import suppress

import pythoncom
import win32com.client

logger = logging.getLogger(__name__)

# Connection modes
# 1 = localQBD          (QB must be running, uses current company)
# 2 = remoteQBD         (rare)
# 3 = localQBDLaunchUI  (launches QB if not running)
CONN_MODE_LOCAL = 1
CONN_MODE_LAUNCH_UI = 3

# Open mode
# 1 = single user, 2 = multi user, 0 = do not care
OPEN_MODE_DONT_CARE = 0
OPEN_MODE_SINGLE = 1
OPEN_MODE_MULTI = 2


class QBConnectionError(Exception):
    """Raised when QB connection or session operations fail."""


class QBSession:
    """
    Manages a QuickBooks Desktop session via QBXMLRP2.

    Usage:
        with QBSession(app_name="MyExtractor") as qb:
            response_xml = qb.process_request(request_xml)
    """

    def __init__(
        self,
        app_name: str,
        app_id: str = "",
        company_file: str = "",
        connection_mode: int = CONN_MODE_LOCAL,
        open_mode: int = OPEN_MODE_DONT_CARE,
        qbxml_version: str = "16.0",
    ):
        """
        Args:
            app_name: Name shown in QB's Integrated Applications list. The first
                connection will prompt the QB user to authorize this app_name.
            app_id: Optional unique app identifier (usually empty).
            company_file: Path to .QBW file. Empty string = use currently open file.
            connection_mode: 1 = local (QB must be running), 3 = launch QB UI if needed.
            open_mode: 0 = don't care, 1 = single-user, 2 = multi-user.
            qbxml_version: QBXML spec version. 16.0 is current as of QB 2024+.
                Older company files may require a lower version. Common: 13.0, 14.0, 15.0, 16.0.
        """
        self.app_name = app_name
        self.app_id = app_id
        self.company_file = company_file
        self.connection_mode = connection_mode
        self.open_mode = open_mode
        self.qbxml_version = qbxml_version

        self._rp: object | None = None
        self._ticket: str | None = None
        self._connected = False

    def __enter__(self) -> QBSession:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def open(self) -> None:
        """Open connection and begin session."""
        if self._connected:
            raise QBConnectionError("Session already open")

        try:
            # COM init for current thread
            pythoncom.CoInitialize()

            logger.info("Creating QBXMLRP2 request processor")
            self._rp = win32com.client.Dispatch("QBXMLRP2.RequestProcessor")

            logger.info(
                "Opening connection: app_name=%r mode=%d", self.app_name, self.connection_mode
            )
            self._rp.OpenConnection2(self.app_id, self.app_name, self.connection_mode)

            logger.info(
                "Beginning session: company_file=%r open_mode=%d",
                self.company_file or "<currently open>",
                self.open_mode,
            )
            self._ticket = self._rp.BeginSession(self.company_file, self.open_mode)

            self._connected = True
            logger.info("QB session established (ticket acquired)")

        except Exception as e:
            # Roll back partial state
            self._safe_cleanup()
            raise QBConnectionError(f"Failed to open QB session: {e}") from e

    def close(self) -> None:
        """Close session and connection cleanly."""
        if not self._connected:
            return
        self._safe_cleanup()
        logger.info("QB session closed")

    def _safe_cleanup(self) -> None:
        """Best-effort cleanup, swallowing errors so one failure doesn't block others."""
        if self._rp is not None and self._ticket is not None:
            try:
                self._rp.EndSession(self._ticket)
            except Exception as e:
                logger.warning("EndSession raised: %s", e)
            self._ticket = None

        if self._rp is not None:
            try:
                self._rp.CloseConnection()
            except Exception as e:
                logger.warning("CloseConnection raised: %s", e)
            self._rp = None

        with suppress(Exception):
            pythoncom.CoUninitialize()

        self._connected = False

    def process_request(self, qbxml_request: str) -> str:
        """
        Send a QBXML request to QuickBooks and return the response XML.

        Args:
            qbxml_request: Full QBXML document (including <?xml?> and <?qbxml?> prolog).

        Returns:
            QBXML response document as a string.
        """
        if not self._connected:
            raise QBConnectionError("Session not open")
        return self._rp.ProcessRequest(self._ticket, qbxml_request)

    def get_company_file_path(self) -> str:
        """Returns the path of the currently open company file."""
        if not self._connected:
            raise QBConnectionError("Session not open")
        return self._rp.GetCurrentCompanyFileName(self._ticket)


def wrap_qbxml(body: str, version: str = "16.0", on_error: str = "stopOnError") -> str:
    """
    Wrap an inner QBXML request body in the required envelope.

    Args:
        body: The inner request, e.g. '<InvoiceQueryRq>...</InvoiceQueryRq>'
        version: QBXML version (must match what your QB supports).
        on_error: 'stopOnError' (default) or 'continueOnError'.
    """
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<?qbxml version="{version}"?>\n'
        "<QBXML>\n"
        f'  <QBXMLMsgsRq onError="{on_error}">\n'
        f"    {body}\n"
        "  </QBXMLMsgsRq>\n"
        "</QBXML>"
    )
