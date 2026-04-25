# Parallel Development Workflow with Devin CLI

This directory contains scripts to run multiple Devin AI agents in parallel, each working on a different milestone of the Glasshouse project.

## Prerequisites

- **conda** (Miniconda or Anaconda) for Python environment management
- **Node.js 18+** for frontend development
- **Devin CLI** installed and authenticated

## Overview

The Glasshouse project has milestones that can be developed in parallel:

```
Phase 1 (parallel):
  M0: Static React Flow mockup (frontend)
  M1: Compiler tuning harness (backend)
  M2: Architect agent + contract I/O (backend)
           ↓
         M3: Phase 1 loop end-to-end (depends on M0, M1, M2)
           ↓
Phase 2 (parallel):
  M4: Editable graph + provenance
  M5: Phase 2 orchestrator
           ↓
         M6: Polish + stretch
```

## Quick Start

```bash
# 1. Setup git worktrees AND conda environment (Python 3.10)
./setup-worktrees.sh

# 2. Activate the conda environment
conda activate glasshouse

# 3. Launch Devin agents in parallel (uses tmux if available)
./run-parallel-agents.sh

# 4. Monitor progress
./status.sh

# 5. When agents complete, merge all branches
./merge-milestones.sh main feat/m0-static-mockup feat/m1-compiler-harness feat/m2-architect-contract-io
```

## Environment Setup

The `setup-worktrees.sh` script automatically creates:

1. **Conda environment** named `glasshouse` with Python 3.10
2. **Git worktrees** for each parallel milestone

### Python Backend (M1, M2)
```bash
conda activate glasshouse
cd backend/
pip install -r requirements.txt
```

### Frontend (M0)
```bash
cd frontend/
npm install
```

## How It Works

### Git Worktrees

Each milestone gets its own **git worktree** - a separate working directory with its own branch:

```
/Users/steph/Desktop/
├── IterViz/                    # Main repo (main branch)
└── IterViz-worktrees/          # Worktree directory
    ├── m0-static-mockup/       # feat/m0-static-mockup branch
    ├── m1-compiler-harness/    # feat/m1-compiler-harness branch
    └── m2-architect-contract-io/ # feat/m2-architect-contract-io branch
```

This allows:
- Multiple agents to work simultaneously without conflicts
- Each agent has full git history and can commit independently
- Clean isolation - changes in one worktree don't affect others

### Merge Strategy with `git merge-tree`

The `merge-milestones.sh` script uses `git merge-tree` to:

1. **Detect conflicts before merging** - shows exactly which files conflict
2. **Preview merge results** - no changes until you're ready
3. **Sequential merging** - merges each branch one at a time with clear error handling

### Running Devin Agents

Option 1: **Interactive (one at a time)**
```bash
./run-devin.sh m0  # Start M0 agent interactively
```

Option 2: **Parallel with tmux**
```bash
./run-parallel-agents.sh  # Opens tmux session with all agents
tmux attach -t glasshouse-dev  # Attach to view
```

Option 3: **Manual in separate terminals**
```bash
# Terminal 1
cd ../IterViz-worktrees/m0-static-mockup
devin "$(cat ../../IterViz/scripts/parallel-dev/prompts/m0-static-mockup.md)"

# Terminal 2
cd ../IterViz-worktrees/m1-compiler-harness
devin "$(cat ../../IterViz/scripts/parallel-dev/prompts/m1-compiler-harness.md)"

# Terminal 3
cd ../IterViz-worktrees/m2-architect-contract-io
devin "$(cat ../../IterViz/scripts/parallel-dev/prompts/m2-architect-contract-io.md)"
```

## Directory Structure

```
scripts/parallel-dev/
├── README.md                    # This file
├── setup-worktrees.sh          # Create git worktrees
├── run-devin.sh                # Run single Devin agent
├── run-parallel-agents.sh      # Launch all agents in parallel
├── merge-milestones.sh         # Merge branches with conflict detection
├── status.sh                   # Check status of all branches
├── prompts/                    # Milestone-specific prompts for Devin
│   ├── m0-static-mockup.md
│   ├── m1-compiler-harness.md
│   └── m2-architect-contract-io.md
└── logs/                       # Agent logs (created at runtime)
```

## Handling Merge Conflicts

If `merge-milestones.sh` detects conflicts:

1. **View the conflicts** - The script shows which files conflict
2. **Options**:
   - Fix conflicts in the source branches before merging
   - Use `--skip-conflicts` to merge only clean branches
   - Use `--force` to attempt merge and manually resolve

Example with conflicts:
```bash
# Preview conflicts
./merge-milestones.sh main feat/m0-static-mockup feat/m1-compiler-harness

# If frontend/package.json conflicts, fix in m0 branch first:
cd ../IterViz-worktrees/m0-static-mockup
# ... fix the conflict ...
git add package.json && git commit -m "fix: resolve package.json conflict"

# Then re-run merge
./merge-milestones.sh main feat/m0-static-mockup feat/m1-compiler-harness
```

## Tips

1. **Check status frequently**: Run `./status.sh` to see which branches have new commits

2. **Review before merging**: Look at each branch's commits before merging
   ```bash
   git log main..feat/m0-static-mockup --oneline
   ```

3. **Test after merging**: After merging M0+M1+M2, verify both frontend and backend work together

4. **Create checkpoints**: After successful merges, tag them
   ```bash
   git tag -a phase1-complete -m "M0, M1, M2 merged successfully"
   ```

## Phase 2 Development

After M3 is complete, set up Phase 2 milestones:

```bash
# Add worktrees for M4 and M5
git worktree add ../IterViz-worktrees/m4-editable-graph feat/m4-editable-graph
git worktree add ../IterViz-worktrees/m5-phase2-orchestrator feat/m5-phase2-orchestrator

# Run agents in parallel again
# (update run-parallel-agents.sh with M4/M5 milestones)
```
