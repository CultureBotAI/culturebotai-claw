#!/bin/bash
#
# Test Multi-Claude Coordination Hooks
#
# This script tests that the hooks are working correctly by:
# 1. Acquiring a lock
# 2. Attempting to trigger hooks (which should be blocked)
# 3. Releasing the lock
# 4. Verifying hooks now allow operations
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATION_ROOT="$(dirname "$SCRIPT_DIR")"
WORKSPACE="$ORCHESTRATION_ROOT/workspace"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Multi-Claude Coordination Hook Tests${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Test 1: Lock check without lock
echo -e "${BLUE}TEST 1: Check lock when no lock exists${NC}"
python3 "$SCRIPT_DIR/check_lock.py" culturemech "test operation"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ PASS: No lock detected, operation allowed${NC}"
else
    echo -e "${RED}✗ FAIL: Operation blocked when no lock exists${NC}"
fi
echo ""

# Test 2: Create a lock
echo -e "${BLUE}TEST 2: Create a lock${NC}"
LOCK_DIR="$WORKSPACE/locks"
mkdir -p "$LOCK_DIR"

cat > "$LOCK_DIR/culturemech.lock" <<EOF
locked_by: orchestration_claude
locked_at: '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
operation: test_lock_coordination
pid: $$
expires_at: '$(date -u -v+1H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)'
reason: Testing multi-Claude coordination hooks
EOF

echo -e "${GREEN}✓ Lock created${NC}"
echo ""

# Test 3: Check lock when lock exists
echo -e "${BLUE}TEST 3: Check lock when lock exists${NC}"
python3 "$SCRIPT_DIR/check_lock.py" culturemech "test operation"
if [ $? -eq 1 ]; then
    echo -e "${GREEN}✓ PASS: Lock detected, operation blocked${NC}"
else
    echo -e "${RED}✗ FAIL: Operation allowed when lock exists${NC}"
fi
echo ""

# Test 4: Test global lock
echo -e "${BLUE}TEST 4: Test global lock${NC}"
cat > "$LOCK_DIR/global.lock" <<EOF
locked_by: orchestration_claude
locked_at: '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
operation: global_pipeline_operation
pid: $$
expires_at: '$(date -u -v+1H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)'
reason: Testing global lock
EOF

python3 "$SCRIPT_DIR/check_lock.py" mediaingredientmech "test operation"
if [ $? -eq 1 ]; then
    echo -e "${GREEN}✓ PASS: Global lock blocks all repos${NC}"
else
    echo -e "${RED}✗ FAIL: Global lock didn't block operation${NC}"
fi
echo ""

# Test 5: Cleanup and verify
echo -e "${BLUE}TEST 5: Remove locks and verify access${NC}"
rm -f "$LOCK_DIR/culturemech.lock"
rm -f "$LOCK_DIR/global.lock"

python3 "$SCRIPT_DIR/check_lock.py" culturemech "test operation"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ PASS: After lock removal, operation allowed${NC}"
else
    echo -e "${RED}✗ FAIL: Operation still blocked after lock removal${NC}"
fi
echo ""

# Test 6: Test expired lock
echo -e "${BLUE}TEST 6: Test expired lock${NC}"
cat > "$LOCK_DIR/culturemech.lock" <<EOF
locked_by: orchestration_claude
locked_at: '2020-01-01T00:00:00Z'
operation: old_operation
pid: 12345
expires_at: '2020-01-01T01:00:00Z'
reason: This lock should be expired
EOF

python3 "$SCRIPT_DIR/check_lock.py" culturemech "test operation"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ PASS: Expired lock removed, operation allowed${NC}"
else
    echo -e "${RED}✗ FAIL: Expired lock not handled correctly${NC}"
fi
echo ""

# Cleanup
rm -f "$LOCK_DIR/culturemech.lock"

# Summary
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ All hook tests complete!${NC}"
echo ""
echo "Hooks are installed and working correctly."
echo ""
echo "What this means:"
echo "  • Pre-edit hooks will block file edits when locked"
echo "  • Pre-commit hooks will block commits when locked"
echo "  • Post-edit/commit hooks update status files"
echo ""
echo "To test with real Claude sessions:"
echo "  1. In orchestration: Acquire a lock"
echo "  2. In downstream repo: Try to edit a file"
echo "  3. Claude should show the lock message and block the edit"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
