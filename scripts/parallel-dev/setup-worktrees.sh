#!/bin/bash
# Setup git worktrees for parallel milestone development
# Each worktree gets its own branch for isolated development
# Also creates conda environments for Python backend work

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
WORKTREE_BASE="$REPO_ROOT/../IterViz-worktrees"
PYTHON_VERSION="3.10"
CONDA_ENV_NAME="glasshouse"

echo "🔧 Setting up parallel development environment..."
echo "   Worktree base: $WORKTREE_BASE"
echo "   Python version: $PYTHON_VERSION"
echo ""

# Check for conda
if ! command -v conda &> /dev/null; then
    echo "⚠️  conda not found. Please install Miniconda or Anaconda first."
    echo "   https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

# Create shared conda environment if it doesn't exist
echo "🐍 Setting up conda environment: $CONDA_ENV_NAME"
if conda env list | grep -q "^$CONDA_ENV_NAME "; then
    echo "   ✅ Environment already exists"
else
    echo "   📦 Creating environment with Python $PYTHON_VERSION..."
    conda create -n "$CONDA_ENV_NAME" python="$PYTHON_VERSION" -y
    echo "   ✅ Environment created"
fi

# Ensure we're on main and up to date
git checkout main 2>/dev/null || git checkout -b main
git pull origin main 2>/dev/null || true

# Create worktree base directory
mkdir -p "$WORKTREE_BASE"

# Define milestones that can run in parallel
# Phase 1: M0, M1, M2 can run in parallel
# Phase 2: M4, M5 can run in parallel (after M3)
PARALLEL_MILESTONES=(
    "m0-static-mockup"
    "m1-compiler-harness"
    "m2-architect-contract-io"
)

echo ""
echo "📁 Creating worktrees for parallel milestones..."

for milestone in "${PARALLEL_MILESTONES[@]}"; do
    worktree_path="$WORKTREE_BASE/$milestone"
    branch_name="feat/$milestone"
    
    if [ -d "$worktree_path" ]; then
        echo "   ⏭️  Skipping $milestone (already exists)"
        continue
    fi
    
    echo "   📂 Creating worktree: $milestone"
    
    # Create branch if it doesn't exist
    git branch "$branch_name" 2>/dev/null || true
    
    # Create worktree
    git worktree add "$worktree_path" "$branch_name"
    
    echo "      ✅ Created: $worktree_path"
done

echo ""
echo "📋 Worktree Summary:"
git worktree list

echo ""
echo "🎯 Next steps:"
echo "   1. Activate the conda environment: conda activate $CONDA_ENV_NAME"
echo "   2. cd into each worktree directory"
echo "   3. Run Devin CLI with the milestone-specific prompt"
echo "   4. Use 'scripts/parallel-dev/run-devin.sh <milestone>' to start agents"
echo ""
echo "💡 Quick start:"
echo "   conda activate $CONDA_ENV_NAME && ./scripts/parallel-dev/run-parallel-agents.sh"
echo ""
