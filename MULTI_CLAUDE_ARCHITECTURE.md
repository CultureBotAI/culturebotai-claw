# Multi-Claude Architecture - No API Keys Needed

**Date**: March 20, 2026
**Architecture**: Claude Code → Claude Code (No API Keys!)
**Status**: ✅ **Simplified and More Powerful**

---

## Key Insight

Instead of orchestration calling Anthropic API directly, we use **multiple Claude Code sessions** - each with its own Claude access. No API keys needed!

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Orchestration Claude Code                                  │
│  (culturebotai-claw/)                                │
│                                                              │
│  1. Acquires lock: mediaingredientmech                      │
│  2. Creates task file: workspace/tasks/curation_batch.yaml  │
│  3. Waits for completion                                    │
│  4. Releases lock                                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ Task file + Lock
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  MediaIngredientMech Claude Code                            │
│  (MediaIngredientMech/)                                     │
│                                                              │
│  1. Detects new task file (file watcher or manual check)   │
│  2. Reads task: "Curate 5 ingredients, threshold 0.9"      │
│  3. Uses Claude directly (built-in access!)                 │
│  4. Processes ingredients with LLM assistance               │
│  5. Writes results to workspace/results/                    │
│  6. Updates status: "Complete"                              │
└─────────────────────────────────────────────────────────────┘
```

---

## How It Works

### Step 1: Orchestration Creates Task

**Orchestration Claude** creates a task file:

```yaml
# workspace/tasks/curation_batch_20260320_183045.yaml
task_id: curation_batch_20260320_183045
target_repo: mediaingredientmech
operation: batch_curate
status: pending
created_at: '2026-03-20T18:30:45Z'
parameters:
  batch_size: 5
  auto_accept_threshold: 0.9
  min_occurrences: 10
assigned_to: mediaingredientmech_claude
deadline: '2026-03-20T19:30:45Z'
```

### Step 2: MediaIngredientMech Claude Picks Up Task

**MediaIngredientMech Claude** (in its own session):

```
User: "Check for any pending tasks and process them"

Claude: [Reads workspace/tasks/curation_batch_*.yaml]
        Found task: Curate 5 ingredients with auto-accept 0.9

        [Uses built-in Claude access to process ingredients]
        [Generates ontology mappings]
        [Validates with OAK]
        [Auto-accepts high-confidence mappings]

        [Writes results to workspace/results/]
        [Updates task status to "complete"]
```

No API key needed - Claude Code already has Claude access!

### Step 3: Orchestration Checks Results

**Orchestration Claude** polls or checks:

```python
# Wait for task completion
while task_status != "complete":
    time.sleep(10)
    task_status = check_task_status(task_id)

# Read results
results = read_results(task_id)
print(f"Processed: {results['processed']}")
print(f"Auto-accepted: {results['auto_accepted']}")
```

---

## Communication via Files

### Task Files (`workspace/tasks/`)

```yaml
task_id: curation_batch_001
target_repo: mediaingredientmech
operation: batch_curate
status: pending  # pending → in_progress → complete → failed
created_at: '2026-03-20T18:30:45Z'
started_at: null
completed_at: null
parameters:
  batch_size: 5
  auto_accept_threshold: 0.9
  min_occurrences: 10
assigned_to: mediaingredientmech_claude
result_file: null
error: null
```

### Result Files (`workspace/results/`)

```yaml
task_id: curation_batch_001
status: complete
started_at: '2026-03-20T18:31:00Z'
completed_at: '2026-03-20T18:36:30Z'
duration_seconds: 330
results:
  processed: 5
  auto_accepted: 4
  skipped_low_confidence: 1
  skipped_no_suggestion: 0
  failed: 0
  cost_estimate: $0.35  # Estimated based on Claude usage
  suggestions:
    - ingredient: MgSO4•7H2O
      ontology_id: CHEBI:75895
      label: magnesium sulfate heptahydrate
      confidence: 0.95
      action: auto_accepted
    # ...
```

---

## Implementation

### 1. Task Creation (Orchestration)

```python
# In run_pilot_test.py
def create_curation_task(batch_size, threshold, min_occurrences):
    task_id = f"curation_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    task = {
        'task_id': task_id,
        'target_repo': 'mediaingredientmech',
        'operation': 'batch_curate',
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat(),
        'parameters': {
            'batch_size': batch_size,
            'auto_accept_threshold': threshold,
            'min_occurrences': min_occurrences,
        },
        'assigned_to': 'mediaingredientmech_claude',
    }

    task_file = workspace / 'tasks' / f'{task_id}.yaml'
    with open(task_file, 'w') as f:
        yaml.dump(task, f)

    logger.info(f"✓ Created task: {task_id}")
    return task_id
```

### 2. Task Processing (MediaIngredientMech Claude)

**User prompt to MediaIngredientMech Claude**:
```
Check workspace/tasks/ for any pending curation tasks and process them.
For each task:
1. Read the parameters
2. Use your Claude capabilities to curate ingredients
3. Save results to workspace/results/
4. Update task status to complete
```

**Claude response** (in MediaIngredientMech session):
```
I'll check for pending tasks and process them.

[Reads ../culturebotai-claw/workspace/tasks/]
[Finds curation_batch_20260320_183045.yaml]

Processing task: Curate 5 ingredients with threshold 0.9

[Loads unmapped ingredients]
[For each ingredient, uses Claude to suggest mappings]
[Validates suggestions]
[Auto-accepts high-confidence mappings]

Completed:
- Processed: 5 ingredients
- Auto-accepted: 4 (MgSO4·7H2O, CaCl2·2H2O, NaCl, K2HPO4)
- Skipped: 1 (low confidence)

[Saves results to workspace/results/curation_batch_20260320_183045.yaml]
[Updates task status to "complete"]
```

### 3. Result Checking (Orchestration)

```python
def wait_for_task_completion(task_id, timeout=600):
    task_file = workspace / 'tasks' / f'{task_id}.yaml'
    start_time = time.time()

    while time.time() - start_time < timeout:
        with open(task_file, 'r') as f:
            task = yaml.safe_load(f)

        if task['status'] in ['complete', 'failed']:
            # Read results
            result_file = workspace / 'results' / f'{task_id}.yaml'
            if result_file.exists():
                with open(result_file, 'r') as f:
                    return yaml.safe_load(f)

        time.sleep(10)  # Check every 10 seconds

    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")
```

---

## Advantages

### ✅ No API Keys Needed
- Each Claude Code session has built-in Claude access
- No credential management
- No API key rotation
- No billing complexity

### ✅ Full Claude Capabilities
- Each Claude can use full tool access
- Can read files, run code, search
- Better context awareness
- More intelligent decision-making

### ✅ True Multi-Claude Coordination
- Multiple independent Claude sessions
- Lock system prevents conflicts
- Task-based communication
- Asynchronous execution

### ✅ Human Oversight
- User can monitor each Claude's work
- Can intervene if needed
- Can approve high-risk operations
- Full transparency

---

## Updated Workflow

### Automated Mode

1. **Orchestration Claude**:
   ```
   User: "Process 10 ingredients in batch mode"

   Claude:
   - Creates task file
   - Acquires lock on MediaIngredientMech
   - Waits for completion
   - Reports results
   ```

2. **MediaIngredientMech Claude** (separate session):
   ```
   User: "Check for tasks and process them"

   Claude:
   - Finds pending task
   - Processes ingredients using built-in Claude
   - Saves results
   - Marks task complete
   ```

3. **Orchestration Claude**:
   ```
   - Detects completion
   - Reads results
   - Releases lock
   - Generates report
   ```

### Manual Mode (Even Better!)

**User can directly ask MediaIngredientMech Claude**:
```
User: "Process the pending curation task from orchestration"

Claude: [Does the work with full context and intelligence]
```

---

## Communication Protocol

### Task Status Flow

```
pending → in_progress → complete
                     ↘ failed
```

### File Locations

```
workspace/
├── tasks/           ← Orchestration writes tasks here
│   └── curation_batch_*.yaml
├── results/         ← Downstream Claude writes results here
│   └── curation_batch_*.yaml
├── locks/           ← Lock coordination
│   └── mediaingredientmech.lock
└── status/          ← Status tracking
    ├── orchestration_claude_status.yaml
    └── mediaingredientmech_claude_status.yaml
```

---

## Implementation Plan

### Phase 1: Task Management (30 minutes)

1. Create task creation functions in `run_pilot_test.py`
2. Create task polling/waiting functions
3. Create result parsing functions

### Phase 2: Task Processing Guide (15 minutes)

1. Write instructions for MediaIngredientMech Claude
2. Create helper prompts for task processing
3. Document the workflow

### Phase 3: Integration (15 minutes)

1. Update `run_pilot_test.py` to use task-based approach
2. Test with manual MediaIngredientMech Claude session
3. Verify results

---

## Example Session

### Terminal 1: Orchestration Claude

```bash
$ cd culturebotai-claw
$ .venv/bin/python run_pilot_test.py --batch-size 5 --auto-accept-threshold 0.9

[Orchestration Claude]:
✓ Created task: curation_batch_20260320_183045
✓ Lock acquired: mediaingredientmech
⏳ Waiting for MediaIngredientMech Claude to process task...
  Status: pending (0s elapsed)
  Status: in_progress (15s elapsed)
  Status: in_progress (25s elapsed)
✓ Task complete! (300s elapsed)

Results:
- Processed: 5 ingredients
- Auto-accepted: 4
- Skipped: 1
- Duration: 5 minutes
- Estimated cost: $0.35

✓ Lock released: mediaingredientmech
```

### Terminal 2: MediaIngredientMech Claude

```bash
$ cd MediaIngredientMech

User: "Check for pending curation tasks in ../culturebotai-claw/workspace/tasks/ and process them"

Claude: "I'll check for pending tasks.

Found task: curation_batch_20260320_183045
Parameters:
- Batch size: 5
- Auto-accept threshold: 0.9
- Min occurrences: 10

Processing ingredients...

[1/5] MgSO4•7H2O (29 occurrences)
  Searching for ontology mapping...
  Found: CHEBI:75895 - magnesium sulfate heptahydrate
  Confidence: 0.95
  ✓ AUTO-ACCEPTED

[2/5] CaCl2•2H2O (22 occurrences)
  ...

Completed! Saved results to ../culturebotai-claw/workspace/results/"
```

---

## No API Key = Simplified Architecture

**Before** (API key approach):
```
Orchestration → batch_curate.py → LLMCurator → Anthropic API
                                  ↑
                            Needs API key ❌
```

**After** (Multi-Claude approach):
```
Orchestration Claude → Task file → MediaIngredientMech Claude → Built-in Claude
                                                                 ↑
                                                          No API key! ✅
```

---

## Next Steps

1. **Add task management** to `run_pilot_test.py` (30 min)
2. **Create task processing guide** for downstream Claude (15 min)
3. **Test with live Claude sessions** (15 min)
4. **Document the workflow** (15 min)

**Total**: ~75 minutes to full multi-Claude coordination

---

*This is the true power of Claude Code - multiple intelligent agents coordinating work!*
