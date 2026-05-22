"""
Query definitions for each entity we extract.

Two categories:
- Master data: small, full dumps, no date filter
- Transactional: larger, optionally filtered by date range, must use iterator paging
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryDef:
    """Describes one entity extraction."""

    name: str  # Logical name, used as folder/filename
    request_tag: str  # QBXML request element, e.g. 'InvoiceQueryRq'
    is_transactional: bool  # Whether to apply date filter and use iterator
    inner_filters: str = ""  # Static filter XML (overridden for date filters)
    page_size: int = 100  # Records per page (only used when supports_iterator)
    include_line_items: bool = False
    include_linked_txns: bool = False
    # Most QB query types support the iterator/MaxReturned pattern, but small list
    # queries (AccountQueryRq, terms, currencies, price_levels, etc.) and single-record
    # queries (CompanyQueryRq, PreferencesQueryRq) reject it with a QBXML parse error.
    # Set False for those — they go through run_simple_query instead.
    supports_iterator: bool = True
    notes: str = ""


# ----------------------------------------------------------------------------
# Master data queries (small, full dump, no date filter)
# ----------------------------------------------------------------------------

MASTER_QUERIES: list[QueryDef] = [
    QueryDef(
        name="customers",
        request_tag="CustomerQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        page_size=500,  # Customer lists can be large; paginate anyway
        notes="All customers + Customer:Job hierarchy. Parent refs reveal jobs.",
    ),
    QueryDef(
        name="vendors",
        request_tag="VendorQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        page_size=500,
        notes="All vendors including inactive.",
    ),
    QueryDef(
        name="items",
        request_tag="ItemQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        page_size=500,
        notes="All items: service, inventory, non-inventory, group, discount, sales tax, etc.",
    ),
    QueryDef(
        name="accounts",
        request_tag="AccountQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        supports_iterator=False,
        notes="Full chart of accounts.",
    ),
    QueryDef(
        name="classes",
        request_tag="ClassQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        supports_iterator=False,
        notes="Class tracking entries (empty if class tracking is off).",
    ),
    QueryDef(
        name="sales_tax_codes",
        request_tag="SalesTaxCodeQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        supports_iterator=False,
        notes="Tax codes referenced on invoice lines.",
    ),
    QueryDef(
        name="terms_standard",
        request_tag="StandardTermsQueryRq",
        is_transactional=False,
        supports_iterator=False,
        notes="Net-30, etc. Standard payment terms.",
    ),
    QueryDef(
        name="terms_date_driven",
        request_tag="DateDrivenTermsQueryRq",
        is_transactional=False,
        supports_iterator=False,
        notes="Day-of-month payment terms.",
    ),
    QueryDef(
        name="currencies",
        request_tag="CurrencyQueryRq",
        is_transactional=False,
        supports_iterator=False,
        notes="Empty/error if multi-currency is disabled. Safe to fail.",
    ),
    QueryDef(
        name="price_levels",
        request_tag="PriceLevelQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        supports_iterator=False,
        notes="Per-customer price overrides if used.",
    ),
    QueryDef(
        name="customer_messages",
        request_tag="CustomerMsgQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        supports_iterator=False,
        notes="Standard messages stamped on invoices.",
    ),
    QueryDef(
        name="payment_methods",
        request_tag="PaymentMethodQueryRq",
        is_transactional=False,
        inner_filters="<ActiveStatus>All</ActiveStatus>",
        supports_iterator=False,
        notes="Cash, check, ACH, etc.",
    ),
    QueryDef(
        name="company_info",
        request_tag="CompanyQueryRq",
        is_transactional=False,
        supports_iterator=False,
        notes="Single-record company metadata. Useful for currency, fiscal year, address.",
    ),
    QueryDef(
        name="preferences",
        request_tag="PreferencesQueryRq",
        is_transactional=False,
        supports_iterator=False,
        notes="QB preferences. Reveals what features are enabled (multi-currency, class tracking, etc).",
    ),
]


# ----------------------------------------------------------------------------
# Transactional queries (use iterator, support date filter)
# ----------------------------------------------------------------------------

TRANSACTIONAL_QUERIES: list[QueryDef] = [
    QueryDef(
        name="invoices",
        request_tag="InvoiceQueryRq",
        is_transactional=True,
        include_line_items=True,
        include_linked_txns=True,
        page_size=50,  # Smaller page for txns with line items
        notes="Customer invoices with full line detail.",
    ),
    QueryDef(
        name="bills",
        request_tag="BillQueryRq",
        is_transactional=True,
        include_line_items=True,
        include_linked_txns=True,
        page_size=50,
        notes="Vendor bills with expense and item lines.",
    ),
    QueryDef(
        name="credit_memos",
        request_tag="CreditMemoQueryRq",
        is_transactional=True,
        include_line_items=True,
        include_linked_txns=True,
        page_size=50,
        notes="Customer credits (the sibling of invoices).",
    ),
    QueryDef(
        name="vendor_credits",
        request_tag="VendorCreditQueryRq",
        is_transactional=True,
        include_line_items=True,
        include_linked_txns=True,
        page_size=50,
        notes="Vendor credits (sibling of bills).",
    ),
    QueryDef(
        name="receive_payments",
        request_tag="ReceivePaymentQueryRq",
        is_transactional=True,
        include_line_items=False,  # ReceivePaymentQueryRq schema has no IncludeLineItems
        include_linked_txns=True,
        page_size=100,
        notes="Customer payments applied to invoices. Applied-to refs come via IncludeLinkedTxns.",
    ),
    QueryDef(
        name="bill_payment_checks",
        request_tag="BillPaymentCheckQueryRq",
        is_transactional=True,
        include_line_items=False,  # BillPaymentCheckQueryRq schema has no IncludeLineItems
        include_linked_txns=True,
        page_size=100,
        notes="Payments made to vendors via check.",
    ),
    QueryDef(
        name="bill_payment_credit_cards",
        request_tag="BillPaymentCreditCardQueryRq",
        is_transactional=True,
        include_line_items=False,  # BillPaymentCreditCardQueryRq schema has no IncludeLineItems
        include_linked_txns=True,
        page_size=100,
        notes="Payments to vendors via credit card.",
    ),
    QueryDef(
        name="sales_receipts",
        request_tag="SalesReceiptQueryRq",
        is_transactional=True,
        include_line_items=True,
        include_linked_txns=True,
        page_size=50,
        notes="Cash-sale receipts (used instead of invoice + payment when paid at time of sale).",
    ),
    QueryDef(
        name="journal_entries",
        request_tag="JournalEntryQueryRq",
        is_transactional=True,
        include_line_items=True,
        page_size=100,
        notes="Manual journal entries. Reveal adjustments your bookkeeper makes outside normal flow.",
    ),
]


def build_transactional_filters(
    qdef: QueryDef,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """
    Build the inner filter XML for a transactional query.

    Args:
        qdef: The query definition.
        from_date: ISO date 'YYYY-MM-DD' or None.
        to_date: ISO date 'YYYY-MM-DD' or None.

    Returns:
        XML fragment to insert inside the request element.

    Note on element ordering: QBXML is strict about element order. Filters must
    appear BEFORE include flags. Date range goes first, then includes.
    """
    parts: list[str] = []

    if from_date or to_date:
        date_filter = "<TxnDateRangeFilter>"
        if from_date:
            date_filter += f"<FromTxnDate>{from_date}</FromTxnDate>"
        if to_date:
            date_filter += f"<ToTxnDate>{to_date}</ToTxnDate>"
        date_filter += "</TxnDateRangeFilter>"
        parts.append(date_filter)

    if qdef.include_line_items:
        parts.append("<IncludeLineItems>true</IncludeLineItems>")

    if qdef.include_linked_txns:
        parts.append("<IncludeLinkedTxns>true</IncludeLinkedTxns>")

    return "".join(parts)
