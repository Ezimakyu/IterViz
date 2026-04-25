#!/bin/bash
# Launch multiple Devin agents in parallel for different milestones
# Each agent runs in its own terminal/tmux pane

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
WORKTREE_BASE="$REPO_ROOT/../IterViz-worktrees"
PROMPTS_DIR="$REPO_ROOT/scripts/parallel-dev/prompts"
LOG_DIR="$REPO_ROOT/scripts/parallel-dev/logs"

mkdir -p "$LOG_DIR"

# Check if worktrees exist
if [ ! -d "$WORKTREE_BASE" ]; then
    echo "❌ Worktrees not set up. Run setup-worktrees.sh first"
    exit 1
fi

echo "🚀 Launching parallel Devin agents..."
echo ""

# Phase 1 milestones (can run in parallel)
PHASE1_MILESTONES=(
    "m0-static-mockup"
    "m1-compiler-harness"  
    "m2-architect-contract-io"
)

# Check if tmux is available for multi-pane view
if command -v tmux &> /dev/null; then
    echo "📺 Using tmux for parallel terminal view"
    
    # Create a new tmux session
    SESSION_NAME="glasshouse-dev"
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
    tmux new-session -d -s "$SESSION_NAME" -n "agents"
    
    first=true
    for milestone in "${PHASE1_MILESTONES[@]}"; do
        worktree="$WORKTREE_BASE/$milestone"
        prompt_file="$PROMPTS_DIR/$milestone.md"
        log_file="$LOG_DIR/$milestone.log"
        
        if [ ! -d "$worktree" ]; then
            echo "⚠️  Skipping $milestone (worktree not found)"
            continue
        fi
        
        if $first; then
            first=false
            tmux send-keys -t "$SESSION_NAME" "cd '$worktree' && devin --prompt-file '$prompt_file' 2>&1 | tee '$log_file'" C-m
        else
            tmux split-window -t "$SESSION_NAME" -h
            tmux send-keys -t "$SESSION_NAME" "cd '$worktree' && devin --prompt-file '$prompt_file' 2>&1 | tee '$log_file'" C-m
        fi
    done
    
    # Balance the panes
    tmux select-layout -t "$SESSION_NAME" tiled
    
    echo ""
    echo "✅ Agents launched in tmux session: $SESSION_NAME"
    echo "   Run: tmux attach -t $SESSION_NAME"
    echo "   Logs: $LOG_DIR/"
    
else
    echo "📺 tmux not found - launching in background with logs"
    
    for milestone in "${PHASE1_MILESTONES[@]}"; do
        worktree="$WORKTREE_BASE/$milestone"
        prompt_file="$PROMPTS_DIR/$milestone.md"
        log_file="$LOG_DIR/$milestone.log"
        
        if [ ! -d "$worktree" ]; then
            echo "⚠️  Skipping $milestone (worktree not found)"
            continue
        fi
        
        echo "🔄 Starting $milestone..."
        
        # Run devin in background with logging
        (
            cd "$worktree"
            devin --prompt-file "$prompt_file" > "$log_file" 2>&1
        ) &
        
        PID=$!
        echo "   PID: $PID"
        echo "   Log: $log_file"
        echo "$PID" > "$LOG_DIR/$milestone.pid"
    done
    
    echo ""
    echo "✅ Agents launched in background"
    echo "   Monitor with: tail -f $LOG_DIR/*.log"
    echo "   Check status: ps aux | grep devin"
fi

echo ""
echo "📋 Next steps after agents complete:"
echo "   1. Review each branch's changes"
echo "   2. Run: ./scripts/parallel-dev/merge-milestones.sh main feat/m0-static-mockup feat/m1-compiler-harness feat/m2-architect-contract-io"
echo "   3. Continue with M3 once merged"
