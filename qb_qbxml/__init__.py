"""Shared QuickBooks Desktop COM primitive (QBXMLRP2 RequestProcessor).

Low-level wrapper used by host-side components that talk to QB, such as
``qb_extract`` (bulk export). It holds no extraction or server logic — only
QB session open/ProcessRequest/close plus the QBXML envelope helper.
Windows-only (pywin32 + QBXMLRP2).
"""

from .connection import QBConnectionError, QBSession, wrap_qbxml

__all__ = ["QBConnectionError", "QBSession", "wrap_qbxml"]
