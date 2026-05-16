#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PURGE=false
for arg in "$@"; do
    [[ "$arg" == "--purge" ]] && PURGE=true
done

echo "=== OCI Cost Optimizer — Uninstall ==="

# Remove scheduler entry
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [[ -n "$PYTHON" ]]; then
    "$PYTHON" "$PROJECT_DIR/scripts/setup_schedule.py" uninstall 2>/dev/null || true
fi

if $PURGE; then
    echo "Purging venv and reports (config files preserved)..."
    rm -rf "$PROJECT_DIR/venv"
    rm -rf "$PROJECT_DIR/reports"
    echo "Removed: venv/, reports/"
    echo "Preserved: config/config.yaml, config/.env"
fi

echo "Uninstall complete."
