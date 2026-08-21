#!/bin/bash
#
# Install Multi-Claude Coordination Hooks
#
# This script installs pre-edit, pre-commit, post-edit, and post-commit hooks
# in each downstream repository to enable multi-Claude coordination.
#
# Usage: ./install_hooks.sh [--force]
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATION_ROOT="$(dirname "$SCRIPT_DIR")"
HOOK_TEMPLATES="$ORCHESTRATION_ROOT/hook_templates"

# Repository paths (from environment or default)
CULTUREMECH_ROOT="${CULTUREMECH_ROOT:-$ORCHESTRATION_ROOT/../CultureMech}"
MEDIAINGREDIENTMECH_ROOT="${MEDIAINGREDIENTMECH_ROOT:-$ORCHESTRATION_ROOT/../MediaIngredientMech}"
COMMUNITYMECH_ROOT="${COMMUNITYMECH_ROOT:-$ORCHESTRATION_ROOT/../CommunityMech/CommunityMech}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
if [[ "$1" == "--force" ]]; then
    FORCE=true
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Multi-Claude Coordination Hook Installation${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Function to install hooks for a repo
install_hooks_for_repo() {
    local repo_name=$1
    local repo_path=$2

    echo -e "${BLUE}Installing hooks for ${repo_name}...${NC}"

    # Check if repo exists
    if [ ! -d "$repo_path" ]; then
        echo -e "${RED}  ✗ Repository not found: $repo_path${NC}"
        echo -e "${YELLOW}    Skipping ${repo_name}${NC}"
        echo ""
        return 1
    fi

    # Create .claude/hooks directory
    local hooks_dir="$repo_path/.claude/hooks"
    mkdir -p "$hooks_dir"

    # Install each hook
    local hooks=("pre-edit" "pre-commit" "post-edit" "post-commit")
    local installed=0
    local skipped=0

    for hook in "${hooks[@]}"; do
        local template_file="$HOOK_TEMPLATES/$hook"
        local target_file="$hooks_dir/$hook"

        # Check if hook already exists
        if [ -f "$target_file" ] && [ "$FORCE" = false ]; then
            echo -e "${YELLOW}  ⊙ $hook already exists (use --force to overwrite)${NC}"
            skipped=$((skipped + 1))
            continue
        fi

        # Copy and customize hook
        local escaped_root=${ORCHESTRATION_ROOT//&/\\&}
        escaped_root=${escaped_root//|/\\|}
        sed \
            -e "s|{{REPO_NAME}}|$repo_name|g" \
            -e "s|{{ORCHESTRATION_ROOT}}|$escaped_root|g" \
            "$template_file" > "$target_file"
        chmod +x "$target_file"

        echo -e "${GREEN}  ✓ Installed $hook${NC}"
        installed=$((installed + 1))
    done

    echo -e "${GREEN}  Installed: $installed hooks${NC}"
    if [ $skipped -gt 0 ]; then
        echo -e "${YELLOW}  Skipped: $skipped hooks (already exist)${NC}"
    fi
    echo ""

    return 0
}

# Check if hook templates exist
if [ ! -d "$HOOK_TEMPLATES" ]; then
    echo -e "${RED}✗ Hook templates not found: $HOOK_TEMPLATES${NC}"
    exit 1
fi

echo "Orchestration root: $ORCHESTRATION_ROOT"
echo "Hook templates: $HOOK_TEMPLATES"
echo ""

# Install hooks for each repo
echo -e "${BLUE}─────────────────────────────────────────────────────────${NC}"
install_hooks_for_repo "culturemech" "$CULTUREMECH_ROOT"

echo -e "${BLUE}─────────────────────────────────────────────────────────${NC}"
install_hooks_for_repo "mediaingredientmech" "$MEDIAINGREDIENTMECH_ROOT"

echo -e "${BLUE}─────────────────────────────────────────────────────────${NC}"
install_hooks_for_repo "communitymech" "$COMMUNITYMECH_ROOT"

# Summary
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Hook installation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Test hooks: Run check_lock.py manually"
echo "  2. Start downstream Claude sessions"
echo "  3. Verify locks are checked before operations"
echo ""
echo "To verify installation:"
echo "  ls -la $CULTUREMECH_ROOT/.claude/hooks/"
echo "  ls -la $MEDIAINGREDIENTMECH_ROOT/.claude/hooks/"
echo "  ls -la $COMMUNITYMECH_ROOT/.claude/hooks/"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
