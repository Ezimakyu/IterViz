#!/bin/bash
# Check status of all parallel development branches and worktrees

REPO_ROOT=$(git rev-parse --show-toplevel)
WORKTREE_BASE="$REPO_ROOT/../IterViz-worktrees"
LOG_DIR="$REPO_ROOT/scripts/parallel-dev/logs"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Glasshouse Parallel Development Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📁 Worktrees:"
git worktree list
echo ""

echo "🌿 Branch Status:"
echo ""

MILESTONES=(
    "m0-static-mockup"
    "m1-compiler-harness"
    "m2-architect-contract-io"
)

for milestone in "${MILESTONES[@]}"; do
    branch="feat/$milestone"
    worktree="$WORKTREE_BASE/$milestone"
    
    echo "  $milestone:"
    
    # Check if branch exists
    if git show-ref --verify --quiet "refs/heads/$branch"; then
        # Get commit count ahead of main
        AHEAD=$(git rev-list main..$branch --count 2>/dev/null || echo "?")
        LAST_COMMIT=$(git log -1 --format="%h %s" "$branch" 2>/dev/null || echo "no commits")
        echo "    Branch: ✅ exists ($AHEAD commits ahead of main)"
        echo "    Latest: $LAST_COMMIT"
    else
        echo "    Branch: ⏳ not created yet"
    fi
    
    # Check worktree status
    if [ -d "$worktree" ]; then
        cd "$worktree"
        CHANGES=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CHANGES" -gt 0 ]; then
            echo "    Worktree: 📝 $CHANGES uncommitted changes"
        else
            echo "    Worktree: ✅ clean"
        fi
        cd "$REPO_ROOT"
    else
        echo "    Worktree: ⏳ not created"
    fi
    
    # Check if agent is running
    if [ -f "$LOG_DIR/$milestone.pid" ]; then
        PID=$(cat "$LOG_DIR/$milestone.pid")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "    Agent: 🔄 running (PID $PID)"
        else
            echo "    Agent: ✅ completed"
        fi
    fi
    
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔧 Quick Commands:"
echo "   Setup worktrees:    ./scripts/parallel-dev/setup-worktrees.sh"
echo "   Launch agents:      ./scripts/parallel-dev/run-parallel-agents.sh"
echo "   Check status:       ./scripts/parallel-dev/status.sh"
echo "   Merge branches:     ./scripts/parallel-dev/merge-milestones.sh main feat/m0-* feat/m1-* feat/m2-*"
