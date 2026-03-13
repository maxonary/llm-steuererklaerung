# Current Architecture Status

## How It Works Now

1. `sync-gmail` ingests invoice PDFs from Gmail, categorizes them, moves them into `Invoices/<Category>/`, indexes metadata in `data/invoice_index.db`, and can label Gmail messages.
   - Example: `python3 main.py sync-gmail --window-months 18 --apply-labels`
   - Optional fixed start date: `--since YYYY/MM/DD`
   - Optional no Gmail changes: `--no-apply-labels`

2. `find` searches invoices from SQLite (fast, no folder scanning).
   - Example: `python3 main.py find --vendor bahn --year 2026`
   - Example: `python3 main.py find --status needs_review --open-gmail-link`

3. `export-accountant` builds accountant handoff packages.
   - Example: `python3 main.py export-accountant --year 2026 --month 1`
   - Writes ZIP + CSV manifest in `Exports/YYYY/YYYY-MM/`.

4. `reindex` rebuilds the DB from existing `Invoices/` files.
   - `python3 main.py reindex`

5. Legacy commands still work (`--scan-gmail`, `--process-local`, `--full-run`, travel report and Bewirtungsbeleg flags).

## What Is Still Missing

- No automated tests added yet (only syntax + CLI help checks).
- No migration command for old data beyond one-time `review_queue.csv` import at startup.
- `find --open-gmail-link` currently prints links; it does not open a browser automatically.
- Gmail link extraction is heuristic (HTML anchor filtering), not LLM-assisted like before.
- No background scheduler/daemon yet (sync is still manual command-based).
- No Streamlit integration with the new SQLite index yet (Streamlit remains mostly separate).
- Export format is DATEV-friendly generic, but not a strict DATEV Belegtransfer-specific schema/import package.
