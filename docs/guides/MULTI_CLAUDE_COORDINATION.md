# Multi-Claude Instance Coordination Strategy

**Critical Issue**: Multiple Claude Code instances running concurrently across 4 repositories need coordination to prevent conflicts, data corruption, and interference.

**Date**: March 18, 2026
**Priority**: 🔴 **CRITICAL**

---

## Problem Statement

### Current Architecture

```
Orchestration Repo (culturebotai-claw/)
├── Orchestration Claude ⭐ (THIS INSTANCE)
│   └── Coordinates agents across all repos
│
Downstream Repos:
├── CultureMech/
│   └── CultureMech Claude 🔵
│       └── Handles CultureMech-specific work
│
├── MediaIngredientMech/
│   └── MediaIngredientMech Claude 🟢
│       └── Handles MediaIngredientMech-specific work
│
└── CommunityMech/
    └── CommunityMech Claude 🟡
        └── Handles CommunityMech-specific work
```

### Conflict Risks

1. **File Conflicts**: Multiple Claudes editing same files simultaneously
2. **Git Conflicts**: Concurrent commits, branch creation, push operations
3. **Data Races**: Pipeline reading while downstream Claude is writing
4. **Resource Contention**: Concurrent justfile execution, test runs
5. **Cost Duplication**: Multiple Claudes calling LLMs for same task
6. **Inconsistent State**: Orchestration sees stale data while downstream modifies

---

## Coordination Architecture

### 1. Role-Based Division of Labor

**Orchestration Claude (⭐ Coordinator)**:
- **Responsibilities**:
  - Pipeline orchestration
  - Cross-repo data synchronization
  - High-level task planning
  - Monitoring and reporting
  - Inter-repo communication
- **Constraints**:
  - READ-ONLY access to downstream repos (no direct edits)
  - Must delegate actual work to downstream Claudes
  - Can only call justfile commands, not edit source code
- **Communication**: Via lock files and status files

**Downstream Claudes (🔵🟢🟡 Workers)**:
- **Responsibilities**:
  - Execute work within their repo
  - File editing, code changes
  - Local testing and validation
  - Git operations (commit, branch)
- **Constraints**:
  - Work ONLY within their repo boundaries
  - Do NOT initiate cross-repo operations
  - Check lock files before starting work
- **Communication**: Via status files and completion signals

---

## 2. Lock File System

### Implementation

Create a **distributed lock system** using file-based locks:

```
culturebotai-claw/locks/
├── culturemech.lock         # Lock for CultureMech operations
├── mediaingredientmech.lock # Lock for MediaIngredientMech operations
├── communitymech.lock       # Lock for CommunityMech operations
└── global.lock              # Global lock for cross-repo operations
```

### Lock File Format (YAML)

```yaml
locked_by: "orchestration_claude"  # or "culturemech_claude", etc.
locked_at: "2026-03-18T11:00:00Z"
operation: "ingredient_curation_pipeline"
pid: 12345                         # Process ID (if available)
expires_at: "2026-03-18T12:00:00Z" # Auto-expire after 1 hour
reason: "Running batch curation of 50 ingredients"
```

### Lock Protocol

**Acquire Lock**:
1. Check if lock file exists
2. If exists, check if expired
3. If not expired, wait or fail
4. If expired or doesn't exist, create lock file
5. Proceed with work

**Release Lock**:
1. Complete operation
2. Delete lock file
3. Write status file

**Auto-Expire**: Locks expire after 1 hour to prevent deadlocks from crashed processes

---

## 3. Status File System

### Purpose
Allow Claudes to communicate state without direct interaction

### Directory Structure

```
culturebotai-claw/status/
├── orchestration_status.yaml
├── culturemech_status.yaml
├── mediaingredientmech_status.yaml
└── communitymech_status.yaml
```

### Status File Format

```yaml
last_updated: "2026-03-18T11:30:00Z"
status: "idle"  # or "busy", "waiting", "error"
current_operation: null  # or description
last_completed_operation:
  type: "batch_curate"
  timestamp: "2026-03-18T11:25:00Z"
  result: "success"
  details:
    ingredients_processed: 50
    auto_accepted: 35
    cost_usd: 2.45
next_available_at: "2026-03-18T11:30:00Z"
```

### Status Checking Protocol

**Before Starting Work**:
1. Check own repo status
2. Check related repos' status
3. If any related repo is busy with conflicting operation, wait
4. Update own status to "busy"
5. Proceed

**After Completing Work**:
1. Update status to "idle"
2. Write completion details
3. Set next_available_at

---

## 4. Operation Priority System

### Priority Levels

1. **CRITICAL** (P0): Data corruption prevention, emergency repairs
2. **HIGH** (P1): Cross-repo pipeline operations (orchestration)
3. **MEDIUM** (P2): Single-repo operations (downstream work)
4. **LOW** (P3): Background tasks (reports, monitoring)

### Priority Rules

- **Rule 1**: CRITICAL operations can interrupt any other operation
- **Rule 2**: HIGH operations acquire global lock (blocks all downstream)
- **Rule 3**: MEDIUM operations acquire repo-specific lock (blocks only their repo)
- **Rule 4**: LOW operations run only when no locks exist

---

## 5. Communication Protocol

### Orchestration → Downstream

**Method 1: Task Files**
```
culturebotai-claw/tasks/
├── culturemech_task_001.yaml
├── mediaingredientmech_task_002.yaml
└── communitymech_task_003.yaml
```

**Task File Format**:
```yaml
task_id: "mediaingredient_001"
created_at: "2026-03-18T11:00:00Z"
priority: "HIGH"
operation: "batch_curate"
parameters:
  batch_size: 50
  auto_accept_threshold: 0.9
  dry_run: false
status: "pending"  # pending → in_progress → completed → failed
assigned_to: "mediaingredientmech_claude"
```

**Workflow**:
1. Orchestration Claude creates task file
2. Downstream Claude polls task directory
3. Downstream Claude picks up task, sets status to "in_progress"
4. Downstream Claude completes task
5. Downstream Claude sets status to "completed", writes result
6. Orchestration Claude reads result, archives task

**Method 2: Direct Message Files**
```
culturebotai-claw/messages/
├── to_culturemech_001.yaml
├── to_mediaingredientmech_002.yaml
└── to_communitymech_003.yaml
```

### Downstream → Orchestration

**Method 1: Completion Signals**
```
culturebotai-claw/completions/
├── culturemech_completion_001.yaml
├── mediaingredientmech_completion_002.yaml
└── communitymech_completion_003.yaml
```

**Method 2: Status Updates** (via status files)

---

## 6. Conflict Resolution

### Scenario 1: Concurrent File Edit

**Problem**: Orchestration pipeline reads `unmapped_ingredients.yaml` while MediaIngredientMech Claude is editing it

**Solution**:
1. MediaIngredientMech Claude acquires `mediaingredientmech.lock` before editing
2. Orchestration Claude checks lock before reading
3. If locked, wait or skip this cycle
4. MediaIngredientMech Claude releases lock after commit
5. Orchestration Claude can now safely read

### Scenario 2: Pipeline Running During Manual Edit

**Problem**: User asks MediaIngredientMech Claude to edit code while orchestration pipeline is running

**Solution**:
1. MediaIngredientMech Claude checks `locks/mediaingredientmech.lock`
2. If locked by orchestration, respond: "⚠️ Orchestration pipeline is currently running. Wait for completion or ask orchestration Claude to pause."
3. User can either:
   - Wait for pipeline to complete
   - Ask orchestration Claude to pause/cancel pipeline
4. Once lock released, MediaIngredientMech Claude can proceed

### Scenario 3: Git Conflicts

**Problem**: Orchestration commits via downstream Claude while downstream Claude also trying to commit

**Solution**:
1. All git operations require lock
2. **Rule**: Only one Claude can commit at a time
3. Orchestration Claude delegates commits to downstream Claude
4. Downstream Claude acquires lock, commits, releases lock
5. No concurrent commits possible

### Scenario 4: Cost Duplication

**Problem**: Orchestration pipeline calls LLMCurator while MediaIngredientMech Claude independently calls it

**Solution**:
1. Check status files for ongoing operations
2. If operation matches, return error: "⚠️ Operation already in progress by [X] Claude"
3. Suggest waiting or coordinating
4. Track costs in status files to detect duplication

---

## 7. Implementation: Lock Manager Plugin

### File: `plugins/lock_manager.py`

```python
"""
Lock Manager Plugin for Multi-Claude Coordination

Prevents conflicts between Orchestration Claude and downstream Claudes.
"""

import os
import time
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class LockManager:
    """Distributed lock manager for multi-Claude coordination."""

    def __init__(self, locks_dir: Path):
        self.locks_dir = Path(locks_dir)
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        self.my_id = "orchestration_claude"

    def acquire_lock(
        self,
        resource: str,
        operation: str,
        timeout: int = 3600,
        wait: bool = False,
        max_wait: int = 300,
    ) -> bool:
        """
        Acquire a lock on a resource.

        Args:
            resource: Resource name (e.g., "culturemech")
            operation: Description of operation
            timeout: Lock expiration time in seconds
            wait: If True, wait for lock to become available
            max_wait: Maximum wait time in seconds

        Returns:
            True if lock acquired, False otherwise
        """
        lock_file = self.locks_dir / f"{resource}.lock"
        start_time = time.time()

        while True:
            # Check existing lock
            if lock_file.exists():
                with open(lock_file, 'r') as f:
                    lock_data = yaml.safe_load(f)

                # Check if expired
                expires_at = datetime.fromisoformat(lock_data['expires_at'])
                if datetime.utcnow() > expires_at:
                    # Expired, remove it
                    lock_file.unlink()
                else:
                    # Still valid
                    if not wait:
                        return False

                    # Wait and retry
                    if time.time() - start_time > max_wait:
                        return False

                    time.sleep(5)
                    continue

            # Create lock
            lock_data = {
                'locked_by': self.my_id,
                'locked_at': datetime.utcnow().isoformat(),
                'operation': operation,
                'pid': os.getpid(),
                'expires_at': (datetime.utcnow() + timedelta(seconds=timeout)).isoformat(),
                'reason': operation,
            }

            with open(lock_file, 'w') as f:
                yaml.dump(lock_data, f)

            return True

    def release_lock(self, resource: str):
        """Release a lock."""
        lock_file = self.locks_dir / f"{resource}.lock"
        if lock_file.exists():
            lock_file.unlink()

    def check_lock(self, resource: str) -> Optional[Dict[str, Any]]:
        """Check if resource is locked."""
        lock_file = self.locks_dir / f"{resource}.lock"
        if not lock_file.exists():
            return None

        with open(lock_file, 'r') as f:
            lock_data = yaml.safe_load(f)

        # Check expiration
        expires_at = datetime.fromisoformat(lock_data['expires_at'])
        if datetime.utcnow() > expires_at:
            lock_file.unlink()
            return None

        return lock_data
```

---

## 8. Recommended Workflow Patterns

### Pattern 1: Orchestration-Driven Pipeline

```
1. Orchestration Claude:
   - Check all downstream status files
   - If any busy, wait or fail
   - Acquire global lock
   - Create task files for downstream Claudes
   - Wait for completion signals

2. Downstream Claudes:
   - Poll task directory
   - Pick up task, acquire repo lock
   - Execute work
   - Release lock, write completion signal

3. Orchestration Claude:
   - Read completion signals
   - Aggregate results
   - Release global lock
   - Generate report
```

### Pattern 2: Downstream-Initiated Work

```
1. User asks MediaIngredientMech Claude to edit code

2. MediaIngredientMech Claude:
   - Check locks/mediaingredientmech.lock
   - If locked, warn user
   - If not locked, acquire lock
   - Perform edits
   - Commit changes
   - Release lock
   - Update status file
```

### Pattern 3: Emergency Override

```
1. User detects critical issue (data corruption)

2. User tells Orchestration Claude: "EMERGENCY: Stop all operations"

3. Orchestration Claude:
   - Create locks/EMERGENCY.lock (blocks everything)
   - Write to all status files: status="paused"
   - Wait for all Claudes to acknowledge

4. All downstream Claudes:
   - Detect EMERGENCY.lock
   - Stop current operation
   - Acknowledge pause

5. User resolves issue

6. User tells Orchestration Claude: "Resume operations"

7. Orchestration Claude:
   - Remove EMERGENCY.lock
   - Update status files: status="idle"
```

---

## 9. Configuration: Claude Code Settings

### In Each Repo's `.claude/settings.json`

```json
{
  "coordination": {
    "enabled": true,
    "my_id": "culturemech_claude",  // Unique per repo
    "orchestration_root": "/absolute/path/to/culturebotai-claw",
    "check_locks_before": [
      "file_edit",
      "git_commit",
      "git_push",
      "justfile_execution"
    ],
    "update_status_after": [
      "file_edit",
      "git_commit"
    ]
  }
}
```

### Implementation in Claude Code Hooks

```bash
# .claude/hooks/pre-edit
#!/bin/bash
# Check lock before editing files

ORCHESTRATION="${OPENCLAW_ORCHESTRATION_ROOT:?Set OPENCLAW_ORCHESTRATION_ROOT}"
LOCK_FILE="$ORCHESTRATION/locks/culturemech.lock"

if [ -f "$LOCK_FILE" ]; then
    echo "⚠️  CultureMech is locked by orchestration pipeline"
    echo "Lock details:"
    cat "$LOCK_FILE"
    exit 1
fi
```

---

## 10. Immediate Action Items

### Phase 1: Setup (Now)

- [ ] Create directory structure:
  ```bash
  mkdir -p culturebotai-claw/{locks,status,tasks,completions,messages}
  ```

- [ ] Implement LockManager plugin
- [ ] Create initial status files
- [ ] Document coordination protocol

### Phase 2: Integration (Week 4)

- [ ] Integrate lock checks into OpenClaw agents
- [ ] Add status updates to pipeline
- [ ] Test lock acquisition/release
- [ ] Test concurrent operation prevention

### Phase 3: Downstream Setup (Week 5)

- [ ] Configure Claude Code in each downstream repo
- [ ] Add pre-edit hooks for lock checking
- [ ] Add post-edit hooks for status updates
- [ ] Test manual edit while pipeline running

### Phase 4: Production (Week 6)

- [ ] Enable coordination in production
- [ ] Monitor for conflicts
- [ ] Adjust timeouts and priorities
- [ ] Document lessons learned

---

## 11. Key Principles

1. **Orchestration Claude is READ-ONLY** on downstream repos
2. **One lock per operation** - never start without acquiring lock
3. **Always release locks** - even on error (use try/finally)
4. **Auto-expire locks** - prevent deadlocks from crashes
5. **Check status before starting** - avoid duplicate work
6. **Update status after completing** - enable monitoring
7. **Use file-based communication** - simple, debuggable, cross-platform
8. **Priority system** - critical operations can interrupt others
9. **Fail fast** - if can't acquire lock, don't wait indefinitely
10. **Audit everything** - log all lock acquisitions, releases, conflicts

---

## 12. Monitoring Dashboard

### Status Dashboard (HTML/Terminal)

```
Multi-Claude Coordination Dashboard
════════════════════════════════════════════════════════════

Orchestration Claude ⭐
  Status: BUSY
  Operation: ingredient_curation_pipeline
  Started: 11:00:00
  ETA: 11:05:00

CultureMech Claude 🔵
  Status: WAITING
  Waiting for: orchestration to release lock
  Last operation: export_ingredients (completed)

MediaIngredientMech Claude 🟢
  Status: IDLE
  Last operation: batch_curate (completed 5m ago)
  Next available: NOW

CommunityMech Claude 🟡
  Status: IDLE
  Last operation: audit_network (completed 1h ago)
  Next available: NOW

Active Locks:
  • mediaingredientmech.lock (orchestration, expires in 55m)

Recent Conflicts:
  None

Cost Summary:
  Orchestration: $2.45
  MediaIngredientMech: $0.00
  Total: $2.45
```

---

## Summary

**Problem**: Multiple Claude instances need coordination
**Solution**: File-based lock system + status files + task delegation
**Key Components**:
- LockManager plugin
- Status file system
- Task delegation protocol
- Priority system
- Git conflict prevention

**Implementation Priority**: 🔴 **CRITICAL - Must implement before Week 4 testing**

---

**Next Steps**:
1. Create directory structure
2. Implement LockManager plugin
3. Update OpenClaw agents to use locks
4. Test coordination with simulated concurrent operations
5. Document for downstream Claude instances

**Status**: 📋 **DESIGN COMPLETE - Ready for Implementation**
