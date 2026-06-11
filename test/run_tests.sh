#!/usr/bin/env bash
# DendROS test runner — generates a timestamped report in test/reports/
#
# Usage:
#   bash test/run_tests.sh              # unit tests only (default)
#   bash test/run_tests.sh --all        # unit + integration tests
#   bash test/run_tests.sh --docker     # unit + Docker integration only
#   bash test/run_tests.sh --host       # unit + host integration only
#   bash test/run_tests.sh --html       # also generate HTML report (requires pytest-html)
#
# The report is saved to test/reports/report_YYYYMMDD_HHMMSS.txt
# If --html is passed, an HTML report is saved alongside it.
#
# Exit code: 0 if all tests pass, non-zero otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
REPORT_DIR="$SCRIPT_DIR/reports"

mkdir -p "$REPORT_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_TXT="$REPORT_DIR/report_${TIMESTAMP}.txt"
REPORT_HTML="$REPORT_DIR/report_${TIMESTAMP}.html"

# ── Parse flags ───────────────────────────────────────────────────────────────
RUN_INTEGRATION=false
RUN_DOCKER=false
RUN_HOST=false
HTML=false

for arg in "$@"; do
    case "$arg" in
        --all)    RUN_INTEGRATION=true; RUN_DOCKER=true; RUN_HOST=true ;;
        --docker) RUN_INTEGRATION=true; RUN_DOCKER=true ;;
        --host)   RUN_INTEGRATION=true; RUN_HOST=true ;;
        --html)   HTML=true ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

# ── Build pytest args ─────────────────────────────────────────────────────────
PYTEST_BASE=(
    python3 -m pytest
    --tb=long
    -v
    --no-header
    -p no:warnings
    -r a        # show extra summary for all outcomes
)

if $HTML; then
    if python3 -c "import pytest_html" 2>/dev/null; then
        PYTEST_BASE+=(--html="$REPORT_HTML" --self-contained-html)
    else
        echo "WARNING: pytest-html not installed; skipping HTML report."
        echo "         Install with: pip3 install pytest-html"
    fi
fi

# ── Header ────────────────────────────────────────────────────────────────────
{
echo "========================================================================"
echo "  DendROS Test Report — $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================================"
echo ""
} | tee "$REPORT_TXT"

# ── Run unit tests ────────────────────────────────────────────────────────────
UNIT_STATUS=0
echo "── Unit tests ────────────────────────────────────────────────────────" | tee -a "$REPORT_TXT"
set +e
(
    cd "$REPO_ROOT"
    "${PYTEST_BASE[@]}" test/unit/ 2>&1
) | tee -a "$REPORT_TXT"
UNIT_STATUS=${PIPESTATUS[0]}
set -e
echo "" | tee -a "$REPORT_TXT"

# ── Run integration tests (if requested) ──────────────────────────────────────
INTEGRATION_STATUS=0
if $RUN_INTEGRATION; then
    MARK_FILTER=""
    if $RUN_DOCKER && ! $RUN_HOST; then
        MARK_FILTER="-k docker"
    elif $RUN_HOST && ! $RUN_DOCKER; then
        MARK_FILTER="-k host"
    fi

    echo "── Integration tests ─────────────────────────────────────────────────" | tee -a "$REPORT_TXT"
    set +e
    (
        cd "$REPO_ROOT"
        "${PYTEST_BASE[@]}" test/integration/ -m integration $MARK_FILTER 2>&1
    ) | tee -a "$REPORT_TXT"
    INTEGRATION_STATUS=${PIPESTATUS[0]}
    set -e
    echo "" | tee -a "$REPORT_TXT"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
{
echo "========================================================================"
if [[ $UNIT_STATUS -eq 0 && $INTEGRATION_STATUS -eq 0 ]]; then
    echo "  RESULT: ALL TESTS PASSED"
else
    [[ $UNIT_STATUS -ne 0 ]]        && echo "  RESULT: UNIT TESTS FAILED (exit $UNIT_STATUS)"
    [[ $INTEGRATION_STATUS -ne 0 ]] && echo "  RESULT: INTEGRATION TESTS FAILED (exit $INTEGRATION_STATUS)"
fi
echo "  Report: $REPORT_TXT"
$HTML && [[ -f "$REPORT_HTML" ]] && echo "  HTML:   $REPORT_HTML"
echo "========================================================================"
} | tee -a "$REPORT_TXT"

# Return non-zero if anything failed
[[ $UNIT_STATUS -ne 0 || $INTEGRATION_STATUS -ne 0 ]] && exit 1 || exit 0
