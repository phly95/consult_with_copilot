#!/usr/bin/env bash
# consult_with_copilot setup script
# Installs dependencies and Chromium browser

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=== consult_with_copilot setup ==="
echo ""

# Check Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "ERROR: Python 3 not found. Install Python 3.10+ first."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "  macOS: brew install python3"
    echo "  Windows: winget install Python.Python.3.12"
    exit 1
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

echo "Python: $($PYTHON --version)"

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
    echo "Created: $VENV_DIR"
fi

# Install dependencies
echo ""
echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q 2>/dev/null
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" 2>&1 | tail -3

# Install Chromium
echo ""
echo "Installing Chromium browser..."
"$VENV_DIR/bin/playwright" install chromium 2>&1 | tail -2

# Verify
echo ""
echo "Verifying installation..."
ERRORS=0

if "$VENV_DIR/bin/python" -c "import playwright; print(f'  Playwright {playwright.__version__}')" 2>/dev/null; then
    echo "  ✓ Playwright OK"
else
    echo "  ✗ Playwright failed to import"
    ERRORS=$((ERRORS + 1))
fi

if "$VENV_DIR/bin/python" -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.stop()" 2>/dev/null; then
    echo "  ✓ Chromium OK"
else
    echo "  ✗ Chromium failed to launch"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -gt 0 ]; then
    echo ""
    echo "Setup completed with errors. Try:"
    echo "  $VENV_DIR/bin/playwright install chromium"
    exit 1
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo ""
echo "  1. Login (one-time, opens browser):"
echo "     $VENV_DIR/bin/python $SCRIPT_DIR/consult.py login"
echo ""
echo "  2. Test:"
echo "     $VENV_DIR/bin/python $SCRIPT_DIR/consult.py send \"hello\""
echo ""
echo "  3. Check health:"
echo "     $VENV_DIR/bin/python $SCRIPT_DIR/consult.py doctor"
