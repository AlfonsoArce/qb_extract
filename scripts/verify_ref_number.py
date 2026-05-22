"""
One-off verification for the --ref-number filter.

Builds a ground-truth RefNumber -> {TxnID} map from a completed full extraction,
randomly samples N invoice numbers, then queries each one through the SAME
production code path the CLI uses (build_transactional_filters + run_simple_query)
and checks the returned record(s) match the full run exactly.

Usage:
    uv run python scripts/verify_ref_number.py [FULL_RUN_INVOICE_DIR] [N]
"""

from __future__ import annotations

import random
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qb_qbxml.connection import QBSession
from qb_extract.queries import TRANSACTIONAL_QUERIES, build_transactional_filters
from qb_extract.query_runner import run_simple_query


def own_field(ret: ET.Element, tag: str) -> str | None:
    """Direct-child text only — avoids picking up <TxnID>/<RefNumber> nested in <LinkedTxn>."""
    child = ret.find(tag)
    return child.text if child is not None else None


def build_ground_truth(invoice_dir: Path):
    ref_to_txnids: dict[str, set[str]] = defaultdict(set)
    ref_meta: dict[str, tuple[str | None, str | None]] = {}
    pages = sorted(invoice_dir.glob("page_*.xml"))
    for page in pages:
        root = ET.parse(page).getroot()
        for ret in root.iter("InvoiceRet"):
            ref = own_field(ret, "RefNumber")
            txnid = own_field(ret, "TxnID")
            if not ref or not txnid:
                continue
            ref_to_txnids[ref].add(txnid)
            ref_meta.setdefault(ref, (ret.findtext("CustomerRef/FullName"), own_field(ret, "TxnDate")))
    return ref_to_txnids, ref_meta, len(pages)


def main() -> int:
    invoice_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/20260522_124620/txn/invoices")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    print(f"Building ground truth from {invoice_dir} ...")
    ref_to_txnids, ref_meta, npages = build_ground_truth(invoice_dir)
    total_refs = len(ref_to_txnids)
    dup_refs = sum(1 for v in ref_to_txnids.values() if len(v) > 1)
    print(f"  parsed {npages} pages -> {total_refs} distinct RefNumbers "
          f"({dup_refs} reused across >1 invoice)")

    sample = random.sample(sorted(ref_to_txnids), n)
    print(f"\nRandomly selected {n}: {', '.join(sample)}\n")

    inv = next(q for q in TRANSACTIONAL_QUERIES if q.name == "invoices")

    passed = 0
    with QBSession(app_name="QB Data Extractor", company_file="", qbxml_version="16.0") as session:
        for i, ref in enumerate(sample, 1):
            filters = build_transactional_filters(inv, None, None, ref)
            resp = run_simple_query(session, inv.request_tag, filters, "16.0")
            root = ET.fromstring(resp)
            rets = list(root.iter("InvoiceRet"))
            got = {own_field(r, "TxnID") for r in rets}
            ref_consistent = all(own_field(r, "RefNumber") == ref for r in rets)
            expected = ref_to_txnids[ref]
            ok = got == expected and ref_consistent and len(rets) >= 1

            cust, date = ref_meta[ref]
            status = "PASS" if ok else "FAIL"
            print(f"[{i:2d}] {status}  ref={ref:<10} returned={len(rets)} "
                  f"expected_txns={len(expected)}  {date}  {cust}")
            if not ok:
                print(f"        expected TxnIDs: {sorted(expected)}")
                print(f"        got TxnIDs:      {sorted(got)}")
                print(f"        all returned have ref=={ref}? {ref_consistent}")
            passed += ok

    print(f"\n{passed}/{n} passed")
    return 0 if passed == n else 1


if __name__ == "__main__":
    sys.exit(main())
