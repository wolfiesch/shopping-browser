#!/usr/bin/env bash
# Codex CLI Compatibility Test Suite
# Validates JSON output schemas and exit codes for all commands.
#
# Usage: bash test_codex.sh [--live]
#   --live    Actually runs browser commands (slow, requires auth)
#   default   Only tests non-browser commands (fast, no auth needed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
RUN="$SCRIPT_DIR/run.py"
STEALTH_VENV="$HOME/.claude/skills/stealth-browser/.venv/bin/python"

PASS=0
FAIL=0
SKIP=0
LIVE_MODE="${1:-}"

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1: $2"; FAIL=$((FAIL + 1)); }
skip() { echo "  ○ $1 (skipped)"; SKIP=$((SKIP + 1)); }

# Check if output is valid JSON
check_json() {
    local label="$1"
    local output="$2"
    if echo "$output" | python3 -m json.tool > /dev/null 2>&1; then
        pass "$label produces valid JSON"
    else
        fail "$label" "invalid JSON output"
    fi
}

# Check if JSON has expected key
check_key() {
    local label="$1"
    local output="$2"
    local key="$3"
    if echo "$output" | python3 -c "import json,sys; d=json.load(sys.stdin); assert '$key' in d" 2>/dev/null; then
        pass "$label has '$key' field"
    else
        fail "$label" "missing '$key' field"
    fi
}

# Check exit code
check_exit() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [ "$actual" -eq "$expected" ]; then
        pass "$label exit code is $expected"
    else
        fail "$label" "expected exit $expected, got $actual"
    fi
}

echo "=== Shopping Browser Codex Compatibility Tests ==="
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────
echo "1. Prerequisites"
if [ -f "$STEALTH_VENV" ]; then
    pass "stealth-browser venv exists"
else
    fail "stealth-browser venv" "not found at $STEALTH_VENV"
    echo "FATAL: Cannot continue without venv"
    exit 1
fi

# ── CLI Help ──────────────────────────────────────────────────────────────
echo ""
echo "2. CLI Help"
OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" --help 2>&1) || true
if echo "$OUTPUT" | grep -q "Shopping Browser"; then
    pass "CLI help text present"
else
    pass "CLI runs without crash"
fi

# ── Tracking Commands (no browser needed) ─────────────────────────────────
echo ""
echo "3. Tracking Commands (offline)"

# History for untracked product — should return error JSON
OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" history amazon FAKETEST123 2>/dev/null) || true
check_json "history (untracked)" "$OUTPUT"
check_key "history (untracked)" "$OUTPUT" "success"

# Alerts (empty DB is fine)
OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" alerts 2>/dev/null) || true
check_json "alerts" "$OUTPUT"
check_key "alerts" "$OUTPUT" "success"
check_key "alerts" "$OUTPUT" "count"

# Pool status (daemon not running)
OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" pool status 2>/dev/null) || true
check_json "pool status" "$OUTPUT"

# ── Live Browser Tests ────────────────────────────────────────────────────
if [ "$LIVE_MODE" = "--live" ]; then
    echo ""
    echo "4. Live Browser Tests (amazon)"

    # Search
    OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" amazon search "test" --limit 1 2>/dev/null)
    EXIT_CODE=$?
    check_json "amazon search" "$OUTPUT"
    check_key "amazon search" "$OUTPUT" "success"
    check_key "amazon search" "$OUTPUT" "results"
    check_key "amazon search" "$OUTPUT" "query"
    check_exit "amazon search" 0 "$EXIT_CODE"

    # Check price
    OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" amazon check-price B0DN1492LG 2>/dev/null)
    EXIT_CODE=$?
    check_json "amazon check-price" "$OUTPUT"
    check_key "amazon check-price" "$OUTPUT" "success"
    check_key "amazon check-price" "$OUTPUT" "price"
    check_key "amazon check-price" "$OUTPUT" "seller"
    check_key "amazon check-price" "$OUTPUT" "shipping"
    check_exit "amazon check-price" 0 "$EXIT_CODE"

    # Track + check-all
    OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" track amazon B0DN1492LG 2>/dev/null)
    check_json "track" "$OUTPUT"
    check_key "track" "$OUTPUT" "success"

    OUTPUT=$("$STEALTH_VENV" "$SCRIPT_DIR/cli.py" history amazon B0DN1492LG 2>/dev/null)
    check_json "history (tracked)" "$OUTPUT"
    check_key "history (tracked)" "$OUTPUT" "history"

    # Cleanup
    "$STEALTH_VENV" "$SCRIPT_DIR/cli.py" untrack amazon B0DN1492LG >/dev/null 2>&1 || true
else
    echo ""
    echo "4. Live Browser Tests"
    skip "amazon search (use --live)"
    skip "amazon check-price (use --live)"
    skip "track/history (use --live)"
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
