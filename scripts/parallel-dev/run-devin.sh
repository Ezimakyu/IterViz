#!/bin/bash
# Run Devin CLI for a specific milestone
# Usage: ./run-devin.sh <milestone-id> [--background]

set -e

MILESTONE="$1"
BACKGROUND="${2:-}"
REPO_ROOT=$(git rev-parse --show-toplevel)
WORKTREE_BASE="$REPO_ROOT/../IterViz-worktrees"
PROMPTS_DIR="$REPO_ROOT/scripts/parallel-dev/prompts"

if [ -z "$MILESTONE" ]; then
    echo "Usage: $0 <milestone-id> [--background]"
    echo ""
    echo "Available milestones:"
    echo "  m0  - Static React Flow mockup (frontend)"
    echo "  m1  - Compiler tuning harness (backend)"
    echo "  m2  - Architect agent + contract I/O (backend)"
    echo "  m3  - Phase 1 loop end-to-end"
    echo "  m4  - Editable graph + decision provenance"
    echo "  m5  - Phase 2 orchestrator"
    exit 1
fi

# Map short names to full milestone names
case "$MILESTONE" in
    m0) FULL_MILESTONE="m0-static-mockup" ;;
    m1) FULL_MILESTONE="m1-compiler-harness" ;;
    m2) FULL_MILESTONE="m2-architect-contract-io" ;;
    m3) FULL_MILESTONE="m3-phase1-loop" ;;
    m4) FULL_MILESTONE="m4-editable-graph" ;;
    m5) FULL_MILESTONE="m5-phase2-orchestrator" ;;
    *) FULL_MILESTONE="$MILESTONE" ;;
esac

WORKTREE_PATH="$WORKTREE_BASE/$FULL_MILESTONE"
PROMPT_FILE="$PROMPTS_DIR/$FULL_MILESTONE.md"

if [ ! -d "$WORKTREE_PATH" ]; then
    echo "❌ Worktree not found: $WORKTREE_PATH"
    echo "   Run setup-worktrees.sh first"
    exit 1
fi

if [ ! -f "$PROMPT_FILE" ]; then
    echo "❌ Prompt file not found: $PROMPT_FILE"
    exit 1
fi

echo "🚀 Starting Devin for milestone: $FULL_MILESTONE"
echo "   Worktree: $WORKTREE_PATH"
echo "   Prompt: $PROMPT_FILE"
echo ""

cd "$WORKTREE_PATH"

# Read the prompt file
PROMPT=$(cat "$PROMPT_FILE")

if [ "$BACKGROUND" = "--background" ]; then
    echo "Running in background mode..."
    nohup devin --prompt-file "$PROMPT_FILE" > "$WORKTREE_PATH/devin.log" 2>&1 &
    echo "PID: $!"
    echo "Log: $WORKTREE_PATH/devin.log"
else
    # Run Devin interactively
    devin --prompt-file "$PROMPT_FILE"
fi
