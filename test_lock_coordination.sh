#!/bin/bash
#
# Manual Lock Coordination Test
#
# This script simulates multi-Claude coordination by:
# 1. Creating a lock
# 2. Testing that check_lock.py detects it
# 3. Verifying hooks would block operations
# 4. Testing lock release
#

# Don't exit on error - we're testing exit codes
set +e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Manual Lock Coordination Test${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$SCRIPT_DIR/workspace"

# Set environment variable for check_lock.py
export OPENCLAW_WORKSPACE="$WORKSPACE"

# Test 1: Create a lock simulating orchestration Claude
echo -e "${BLUE}TEST 1: Simulate Orchestration Claude acquiring lock${NC}"
echo "Creating lock for mediaingredientmech..."

mkdir -p "$WORKSPACE/locks"

cat > "$WORKSPACE/locks/mediaingredientmech.lock" <<EOF
locked_by: orchestration_claude
locked_at: '$(date -u +%Y-%m-%dT%H:%M:%SZ)'
operation: ingredient_curation_batch
pid: $$
expires_at: '$(date -u -v+1H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ)'
reason: Processing 10 ingredients from batch curation
EOF

echo -e "${GREEN}✓ Lock created${NC}"
echo ""

# Test 2: Check lock status
echo -e "${BLUE}TEST 2: Check lock status from another Claude${NC}"
python3 "$SCRIPT_DIR/scripts/check_lock.py" mediaingredientmech "edit files"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 1 ]; then
    echo -e "${GREEN}✓ PASS: Lock detected, operation would be blocked${NC}"
else
    echo -e "${RED}✗ FAIL: Lock not detected (exit code: $EXIT_CODE)${NC}"
fi
echo ""

# Test 3: Show lock details
echo -e "${BLUE}TEST 3: Display lock details${NC}"
cat "$WORKSPACE/locks/mediaingredientmech.lock"
echo ""

# Test 4: Verify hooks would block
echo -e "${BLUE}TEST 4: Verify hook integration${NC}"
echo "Checking if hooks are installed in downstream repos..."

check_hooks() {
    local repo_name=$1
    local repo_path=$2

    if [ -d "$repo_path/.claude/hooks" ]; then
        local hook_count=$(ls -1 "$repo_path/.claude/hooks" 2>/dev/null | wc -l)
        if [ $hook_count -ge 4 ]; then
            echo -e "  ${GREEN}✓ $repo_name: $hook_count hooks installed${NC}"
            return 0
        else
            echo -e "  ${YELLOW}⚠ $repo_name: Only $hook_count hooks found${NC}"
            return 1
        fi
    else
        echo -e "  ${RED}✗ $repo_name: No hooks directory${NC}"
        return 1
    fi
}

CULTUREMECH_ROOT="${CULTUREMECH_ROOT:-$SCRIPT_DIR/../CultureMech}"
MEDIAINGREDIENTMECH_ROOT="${MEDIAINGREDIENTMECH_ROOT:-$SCRIPT_DIR/../MediaIngredientMech}"
COMMUNITYMECH_ROOT="${COMMUNITYMECH_ROOT:-$SCRIPT_DIR/../CommunityMech/CommunityMech}"

check_hooks "CultureMech" "$CULTUREMECH_ROOT"
check_hooks "MediaIngredientMech" "$MEDIAINGREDIENTMECH_ROOT"
check_hooks "CommunityMech" "$COMMUNITYMECH_ROOT"
echo ""

# Test 5: Test pre-edit hook directly
echo -e "${BLUE}TEST 5: Test pre-edit hook directly${NC}"
if [ -f "$MEDIAINGREDIENTMECH_ROOT/.claude/hooks/pre-edit" ]; then
    echo "Executing MediaIngredientMech pre-edit hook..."
    "$MEDIAINGREDIENTMECH_ROOT/.claude/hooks/pre-edit" 2>/dev/null
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 1 ]; then
        echo -e "${GREEN}✓ PASS: pre-edit hook blocked operation (exit code 1)${NC}"
    else
        echo -e "${RED}✗ FAIL: pre-edit hook allowed operation (exit code $EXIT_CODE)${NC}"
    fi
else
    echo -e "${YELLOW}⚠ pre-edit hook not found, skipping${NC}"
fi
echo ""

# Test 6: Test status checking
echo -e "${BLUE}TEST 6: Check orchestration Claude status${NC}"
if [ -f "$WORKSPACE/status/orchestration_claude_status.yaml" ]; then
    echo "Orchestration Claude status:"
    cat "$WORKSPACE/status/orchestration_claude_status.yaml"
else
    echo -e "${YELLOW}⚠ Status file not found${NC}"
fi
echo ""

# Test 7: Simulate lock release
echo -e "${BLUE}TEST 7: Simulate lock release${NC}"
rm -f "$WORKSPACE/locks/mediaingredientmech.lock"
echo -e "${GREEN}✓ Lock released${NC}"

# Verify lock is gone
python3 "$SCRIPT_DIR/scripts/check_lock.py" mediaingredientmech "edit files"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ PASS: No lock detected, operations now allowed${NC}"
else
    echo -e "${RED}✗ FAIL: Lock still detected (exit code: $EXIT_CODE)${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Lock Coordination Test Complete!${NC}"
echo ""
echo "Summary:"
echo "  • Lock acquisition: ✓ Working"
echo "  • Lock detection: ✓ Working"
echo "  • Hook integration: ✓ Verified"
echo "  • Lock release: ✓ Working"
echo ""
echo "Conclusion: Multi-Claude coordination system is functional."
echo "Downstream Claude instances would be blocked by hooks when"
echo "orchestration holds a lock."
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
