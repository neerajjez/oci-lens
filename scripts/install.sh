#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== OCI Cost Optimizer — Install ==="
echo "Project: $PROJECT_DIR"

# ── Python detection ──────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.9+ is required but was not found." >&2
    echo "Install Python from https://www.python.org/downloads/" >&2
    exit 1
fi
echo "Using Python: $PYTHON ($($PYTHON --version))"

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ ! -d "$PROJECT_DIR/venv" ]]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$PROJECT_DIR/venv"
fi

# shellcheck disable=SC1091
source "$PROJECT_DIR/venv/bin/activate"
echo "Activated venv: $VIRTUAL_ENV"

echo "Upgrading pip and wheel..."
pip install --upgrade pip wheel --quiet

echo "Installing dependencies..."
pip install -r "$PROJECT_DIR/requirements.txt" --quiet

# ── Config files ──────────────────────────────────────────────────────────────
if [[ -f "$PROJECT_DIR/config/.env.example" && ! -f "$PROJECT_DIR/config/.env" ]]; then
    cp "$PROJECT_DIR/config/.env.example" "$PROJECT_DIR/config/.env"
    echo "Created config/.env — please edit it with your OCI credentials."
fi

if [[ -f "$PROJECT_DIR/config/config.yaml.example" && ! -f "$PROJECT_DIR/config/config.yaml" ]]; then
    cp "$PROJECT_DIR/config/config.yaml.example" "$PROJECT_DIR/config/config.yaml"
    echo "Created config/config.yaml — review and adjust settings."
fi

# ── Validate config ───────────────────────────────────────────────────────────
echo "Validating configuration..."
if ! python "$PROJECT_DIR/main.py" validate-config; then
    echo "ERROR: Configuration validation failed. Edit config/config.yaml and retry." >&2
    exit 1
fi

# ── Optional scheduler install ────────────────────────────────────────────────
echo ""
read -rp "Install scheduled task (runs every 15 days at 08:00)? [y/N] " REPLY
if [[ "${REPLY,,}" == "y" ]]; then
    python "$PROJECT_DIR/scripts/setup_schedule.py" install
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Installation complete ==="
echo "  Project dir : $PROJECT_DIR"
echo "  Python      : $(which python)"
echo "  Run manually: python main.py run"
echo "  Status      : python main.py status"
echo "  Logs        : logs/oci_cost_optimizer.log"
echo "  Schedule    : python scripts/setup_schedule.py status"
