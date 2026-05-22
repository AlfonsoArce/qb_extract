# qb_extract

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Managed with uv](https://img.shields.io/badge/managed%20with-uv-261230.svg)](https://docs.astral.sh/uv/)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](#requirements)

QuickBooks Desktop full data extraction toolkit.

Pulls master data (customers, vendors, items, accounts, …) and transactional
data (invoices, bills, payments, journal entries, …) out of a QuickBooks
Desktop company file over the QBXMLRP2 COM interface, saving the raw QBXML
responses plus a run manifest.

## Requirements

- **Windows** with QuickBooks Desktop installed and a company file open
  (the COM interface, `QBXMLRP2.RequestProcessor`, is Windows-only).
- [uv](https://docs.astral.sh/uv/) for environment management.
- Python 3.12+ (uv will fetch it if needed).

## Setup

```powershell
uv sync
```

This creates a `.venv/` and installs dependencies (pywin32) plus dev tools.

## Usage

```powershell
# Pull everything for a date range
uv run python -m qb_extract --from 2024-05-19 --to 2026-05-19

# Master data only (no transactions)
uv run python -m qb_extract --skip-transactional

# Just invoices, for testing
uv run python -m qb_extract --only invoices --from 2026-01-01

# Point at a specific company file (default: the currently-open one)
uv run python -m qb_extract --company-file "C:/QB/MyCompany.QBW" --from 2024-01-01

# Full option list
uv run python -m qb_extract --help
```

On the first run, QuickBooks prompts the logged-in user to authorize the app
(shown as the `--app-name`, default "QB Data Extractor") in its Integrated
Applications list.

Output lands in `./output/<timestamp>/` with raw XML pages, a `manifest.json`,
and an `extraction.log`.

## Layout

- `qb_extract/` — extraction orchestration, query definitions, CLI.
- `qb_qbxml/` — low-level QB COM session wrapper (`QBSession`, `wrap_qbxml`).

## License

Released under the [MIT License](LICENSE).
