#!/bin/bash
#
# Install Multi-Claude Coordination Hooks
#
# This script installs pre-edit, pre-commit, post-edit, and post-commit hooks
# in each downstream repository to enable multi-Claude coordination.
#
# The canonical fleet manifest decides which repositories receive coordination
# hooks. A checkout is targeted only when its manifest-defined environment
# variable is set; no sibling-directory layout is assumed.
#
# Usage: ./install_hooks.sh [--force]
#

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATION_ROOT="$(dirname "$SCRIPT_DIR")"
HOOK_TEMPLATES="$ORCHESTRATION_ROOT/hook_templates"
HOOK_REGISTRAR="$ORCHESTRATION_ROOT/scripts/register_claude_hooks.py"
CONFIGURED_WORKSPACE="${OPENCLAW_WORKSPACE:-workspace}"
MANAGED_HOOK_MARKER="# Managed by kg-microbe coordination hook installer."

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

FORCE=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --force) FORCE=true ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Multi-Claude Coordination Hook Installation${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Function to install hooks for a repo
install_hooks_for_repo() {
    local repo_name=$1
    local repo_path=$2

    echo -e "${BLUE}Installing hooks for ${repo_name}...${NC}"

    # A configured target is an assertion about an exact checkout. Fail closed
    # when it is wrong; only an unset root is a harmless unconfigured target.
    if [ ! -d "$repo_path" ]; then
        echo -e "${RED}  ✗ Repository not found: $repo_path${NC}"
        echo ""
        return 1
    fi

    # RepositorySettings validated the checkout identity before emitting this
    # path. Refuse symlinked hook directories as a second boundary: otherwise
    # mkdir/rendering could escape the validated worktree.
    local hooks_parent="$repo_path/.claude/hooks"
    local hooks_dir="$hooks_parent/kg-microbe"
    if [ -L "$repo_path/.claude" ] || [ -L "$hooks_parent" ] || [ -L "$hooks_dir" ]; then
        echo -e "${RED}  ✗ Hook directory must not be a symlink: $hooks_dir${NC}" >&2
        return 1
    fi

    # Use an owned subdirectory. Generic names such as .claude/hooks/pre-edit
    # may already be user hooks or stale files from the original copier-only
    # installer; never register or overwrite those ambiguous paths.
    if ! mkdir -p "$hooks_dir"; then
        echo -e "${RED}  ✗ Cannot create hooks directory: $hooks_dir${NC}" >&2
        return 1
    fi

    # A restrictive or malformed project-local settings file can make project
    # hooks inactive even when settings.json contains the right handlers.
    # Inspect both settings surfaces before installing any managed file, and
    # repeat the same validation during registration below.
    local settings_file="$repo_path/.claude/settings.json"
    if ! python3 "$HOOK_REGISTRAR" --preflight "$settings_file" >/dev/null; then
        echo -e "${RED}  ✗ Cannot safely activate hooks in $repo_path${NC}" >&2
        return 1
    fi

    # Install each hook and the shared Bash-input classifier used by the two
    # commit hooks. The classifier is deliberately installed alongside the
    # hooks so command filtering does not depend on a caller-controlled PATH.
    local hooks=(
        "pre-edit"
        "pre-bash"
        "pre-commit"
        "post-edit"
        "post-commit"
        "hook-input.py"
    )
    local installed=0
    local skipped=0

    for hook in "${hooks[@]}"; do
        local template_file="$HOOK_TEMPLATES/$hook"
        local target_file="$hooks_dir/$hook"

        # Never treat a symlink or another non-regular path as an installed
        # hook. In particular, -f follows symlinks, so this validation must
        # happen before the ordinary-file skip below.
        if [ -L "$target_file" ]; then
            echo -e "${RED}  ✗ Existing hook target must not be a symlink: $target_file${NC}" >&2
            return 1
        fi
        if [ -e "$target_file" ] && [ ! -f "$target_file" ]; then
            echo -e "${RED}  ✗ Existing hook target must be a regular file: $target_file${NC}" >&2
            return 1
        fi

        # Customize into a temporary file and replace atomically. This keeps an
        # existing hook intact if rendering or chmod fails partway through.
        local shell_root shell_workspace shell_repo_name shell_project_root
        printf -v shell_root '%q' "$ORCHESTRATION_ROOT"
        printf -v shell_workspace '%q' "$COORDINATION_WORKSPACE"
        printf -v shell_repo_name '%q' "$repo_name"
        printf -v shell_project_root '%q' "$repo_path"
        local escaped_root=${shell_root//\\/\\\\}
        escaped_root=${escaped_root//&/\\&}
        escaped_root=${escaped_root//|/\\|}
        local escaped_workspace=${shell_workspace//\\/\\\\}
        escaped_workspace=${escaped_workspace//&/\\&}
        escaped_workspace=${escaped_workspace//|/\\|}
        local escaped_repo_name=${shell_repo_name//\\/\\\\}
        escaped_repo_name=${escaped_repo_name//&/\\&}
        escaped_repo_name=${escaped_repo_name//|/\\|}
        local escaped_project_root=${shell_project_root//\\/\\\\}
        escaped_project_root=${escaped_project_root//&/\\&}
        escaped_project_root=${escaped_project_root//|/\\|}
        local temporary_file
        if ! temporary_file="$(mktemp "$hooks_dir/.${hook}.XXXXXX")"; then
            echo -e "${RED}  ✗ Cannot create a temporary file for $hook${NC}" >&2
            return 1
        fi
        if ! sed \
            -e "s|{{REPO_NAME}}|$escaped_repo_name|g" \
            -e "s|{{ORCHESTRATION_ROOT}}|$escaped_root|g" \
            -e "s|{{WORKSPACE_ROOT}}|$escaped_workspace|g" \
            -e "s|{{PROJECT_ROOT}}|$escaped_project_root|g" \
            "$template_file" > "$temporary_file"; then
            rm -f "$temporary_file"
            echo -e "${RED}  ✗ Cannot render $hook from $template_file${NC}" >&2
            return 1
        fi
        if ! chmod +x "$temporary_file"; then
            rm -f "$temporary_file"
            echo -e "${RED}  ✗ Cannot install $hook at $target_file${NC}" >&2
            return 1
        fi
        if [ -f "$target_file" ] && [ "$FORCE" = false ]; then
            if cmp -s "$temporary_file" "$target_file"; then
                rm -f "$temporary_file"
                echo -e "${YELLOW}  ⊙ $hook is already current${NC}"
                skipped=$((skipped + 1))
                continue
            fi
            if grep -Fqx "$MANAGED_HOOK_MARKER" "$target_file"; then
                echo -e "${YELLOW}  ↻ Upgrading managed $hook${NC}"
            else
                rm -f "$temporary_file"
                echo -e "${RED}  ✗ Managed hook path contains unowned content: $target_file${NC}" >&2
                echo -e "${RED}    Refusing to register it; inspect it and rerun with --force to replace it.${NC}" >&2
                return 1
            fi
        fi
        # Re-check immediately before replacement. A directory created after
        # the initial validation would make mv place the hook inside it and
        # report success instead of installing the requested target.
        if [ -d "$target_file" ]; then
            rm -f "$temporary_file"
            echo -e "${RED}  ✗ Hook destination must not be a directory: $target_file${NC}" >&2
            return 1
        fi
        if [ -L "$target_file" ] || { [ -e "$target_file" ] && [ ! -f "$target_file" ]; }; then
            rm -f "$temporary_file"
            echo -e "${RED}  ✗ Hook destination must be a regular file and not a symlink: $target_file${NC}" >&2
            return 1
        fi
        if ! mv "$temporary_file" "$target_file"; then
            rm -f "$temporary_file"
            echo -e "${RED}  ✗ Cannot install $hook at $target_file${NC}" >&2
            return 1
        fi

        echo -e "${GREEN}  ✓ Installed $hook${NC}"
        installed=$((installed + 1))
    done

    echo -e "${GREEN}  Installed: $installed hook files${NC}"
    if [ $skipped -gt 0 ]; then
        echo -e "${YELLOW}  Skipped: $skipped hook files (already exist)${NC}"
    fi

    # Copying a hook file is not enough for Claude Code to invoke it. Merge our
    # event handlers into project settings after every installation, including
    # idempotent runs where every script above was already present.
    local registration_result
    if ! registration_result="$(python3 "$HOOK_REGISTRAR" "$settings_file")"; then
        echo -e "${RED}  ✗ Cannot register hooks in $settings_file${NC}" >&2
        return 1
    fi
    if [ "$registration_result" = "updated" ]; then
        echo -e "${GREEN}  ✓ Registered Claude Code hook events${NC}"
    else
        echo -e "${YELLOW}  ⊙ Claude Code hook events already registered${NC}"
    fi
    echo ""

    return 0
}

# Check if hook templates exist
if [ ! -d "$HOOK_TEMPLATES" ]; then
    echo -e "${RED}✗ Hook templates not found: $HOOK_TEMPLATES${NC}"
    exit 1
fi
if [ ! -f "$HOOK_REGISTRAR" ] || [ -L "$HOOK_REGISTRAR" ]; then
    echo -e "${RED}✗ Hook registrar must be a regular, non-symlink file: $HOOK_REGISTRAR${NC}" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}✗ python3 is required to register Claude Code hooks safely${NC}" >&2
    exit 1
fi
if ! COORDINATION_WORKSPACE="$(
    python3 "$HOOK_REGISTRAR" --resolve-workspace \
        "$ORCHESTRATION_ROOT" "$CONFIGURED_WORKSPACE"
)"; then
    echo -e "${RED}✗ Cannot resolve a safe coordination workspace${NC}" >&2
    exit 1
fi

echo "Orchestration root: $ORCHESTRATION_ROOT"
echo "Coordination workspace: $COORDINATION_WORKSPACE"
echo "Hook templates: $HOOK_TEMPLATES"
echo ""

# Query through the package CLI rather than parsing YAML in bash. The targets
# command validates each configured checkout's exact GitHub origin before it
# emits the root used below. Its stable TSV contract has no header.
FLEET_TARGET_ARGS=(targets --capability coordination_hooks)
if [ -e "$ORCHESTRATION_ROOT/.env" ] || [ -L "$ORCHESTRATION_ROOT/.env" ]; then
    FLEET_TARGET_ARGS+=(--dotenv "$ORCHESTRATION_ROOT/.env")
fi
if ! FLEET_ROWS="$(
    uv run --offline --frozen --project "$ORCHESTRATION_ROOT" \
        python -m kg_microbe_fleet \
        "${FLEET_TARGET_ARGS[@]}"
)"; then
    echo -e "${RED}✗ Unable to load coordination targets from the fleet manifest${NC}" >&2
    exit 2
fi
if [ -z "$FLEET_ROWS" ]; then
    echo -e "${RED}✗ No Mech enables the coordination_hooks capability${NC}" >&2
    exit 2
fi

configured=0
unconfigured=0
failed=0
while IFS=$'\t' read -r repo_key display_name github_identity root_variable repo_path; do
    if [ -z "$repo_key" ] || [ -z "$display_name" ] || [ -z "$github_identity" ] || [ -z "$root_variable" ]; then
        echo -e "${RED}✗ Malformed fleet CLI row; refusing partial installation${NC}" >&2
        exit 2
    fi

    if [ -z "$repo_path" ]; then
        echo -e "${YELLOW}⊙ ${display_name} is not configured; set ${root_variable}${NC}"
        unconfigured=$((unconfigured + 1))
        continue
    fi

    configured=$((configured + 1))
    echo -e "${BLUE}─────────────────────────────────────────────────────────${NC}"
    if ! install_hooks_for_repo "$repo_key" "$repo_path"; then
        failed=$((failed + 1))
    fi
done <<< "$FLEET_ROWS"

# Summary
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
if [ "$failed" -gt 0 ]; then
    echo -e "${RED}✗ Hook installation failed for ${failed} configured target(s).${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Hook installation complete for ${configured} configured target(s).${NC}"
if [ "$unconfigured" -gt 0 ]; then
    echo -e "${YELLOW}⊙ ${unconfigured} capability-enabled target(s) were not configured.${NC}"
fi
echo ""
echo "Next steps:"
echo "  1. Restart any active downstream Claude Code sessions to load settings."
echo "  2. Open /hooks in each session and confirm project hooks are active."
echo "     User or managed policy is outside this installer's visibility."
echo "  3. Verify edit and Bash tool calls honor coordination locks."
echo ""
echo "To verify installation:"
echo "  Inspect .claude/hooks/kg-microbe/ and project/local settings in each target."
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
