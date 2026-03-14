#!/usr/bin/env bash
set -euo pipefail

MODEL="${OLLAMA_MODEL:-mistral}"

echo "=== 2024 Tax Declaration Workflow ==="
echo ""

# 1. Preflight
echo "[1/6] Preflight checks..."
if ! curl -sf localhost:11434 > /dev/null 2>&1; then
    echo "ERROR: Ollama is not running. Start it with: ollama serve"
    exit 1
fi
echo "  Ollama is running."

if [ ! -f token.pickle ]; then
    echo "ERROR: token.pickle not found. Run Gmail auth first."
    exit 1
fi
echo "  Gmail token found."
echo "  Model: $MODEL"
echo ""

# 2. Sync
echo "[2/6] Syncing Gmail invoices for 2024..."
python3 main.py sync-gmail --since 2024/01/01 --window-months 12 --apply-labels
echo ""

# 3. Review check
echo "[3/6] Checking for items that need manual review..."
python3 main.py find --year 2024 --status needs_review --open-gmail-link || true
echo ""
read -rp "Review the items above and handle any missing PDFs manually. Press Enter to continue..."
echo ""

# 4. Summary
echo "[4/6] Summary of all 2024 invoices:"
python3 main.py find --year 2024
echo ""

# 5. Export
echo "[5/6] Exporting accountant packages for all months of 2024..."
python3 main.py export-accountant --year 2024 --all-months
echo ""

# 6. Done
echo "[6/6] Done!"
echo "  Exports are in: Exports/2024/"
echo "  Reminder: check any remaining 'needs_review' items before sending to your accountant."
