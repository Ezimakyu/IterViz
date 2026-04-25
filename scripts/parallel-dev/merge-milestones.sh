#!/bin/bash
# Merge multiple milestone branches using git merge-tree for conflict detection
# This script automates the merge of parallel milestone branches into a target branch

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
TARGET_BRANCH="${1:-main}"
MILESTONE_BRANCHES=("${@:2}")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

if [ ${#MILESTONE_BRANCHES[@]} -eq 0 ]; then
    echo "Usage: $0 <target-branch> <branch1> <branch2> [branch3...]"
    echo ""
    echo "Example: $0 feat/m3-integration feat/m0-static-mockup feat/m1-compiler-harness feat/m2-architect-contract-io"
    echo ""
    echo "This script will:"
    echo "  1. Check each branch for conflicts with target using merge-tree"
    echo "  2. Report any conflicts before merging"
    echo "  3. Sequentially merge each branch into target"
    echo "  4. Handle merge commits automatically"
    exit 1
fi

cd "$REPO_ROOT"

log_info "Starting merge orchestration"
log_info "Target branch: $TARGET_BRANCH"
log_info "Source branches: ${MILESTONE_BRANCHES[*]}"
echo ""

# Ensure we have latest from all branches
log_info "Fetching latest changes..."
git fetch --all 2>/dev/null || true

# Create or checkout target branch
if git show-ref --verify --quiet "refs/heads/$TARGET_BRANCH"; then
    log_info "Checking out existing branch: $TARGET_BRANCH"
    git checkout "$TARGET_BRANCH"
else
    log_info "Creating new branch: $TARGET_BRANCH from main"
    git checkout -b "$TARGET_BRANCH" main
fi

echo ""
log_info "Phase 1: Conflict detection using merge-tree"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CONFLICTS_FOUND=0
declare -A BRANCH_STATUS

for branch in "${MILESTONE_BRANCHES[@]}"; do
    if ! git show-ref --verify --quiet "refs/heads/$branch"; then
        log_warning "Branch not found: $branch (skipping)"
        BRANCH_STATUS[$branch]="missing"
        continue
    fi
    
    # Use git merge-tree to check for conflicts without actually merging
    # merge-tree outputs conflict info if there are conflicts
    MERGE_BASE=$(git merge-base "$TARGET_BRANCH" "$branch" 2>/dev/null || echo "")
    
    if [ -z "$MERGE_BASE" ]; then
        log_info "$branch: No common ancestor (will merge as new content)"
        BRANCH_STATUS[$branch]="ready"
        continue
    fi
    
    # git merge-tree returns exit 0 and empty output if clean merge possible
    # Otherwise it outputs the merged tree with conflict markers
    MERGE_RESULT=$(git merge-tree "$MERGE_BASE" "$TARGET_BRANCH" "$branch" 2>&1)
    
    if echo "$MERGE_RESULT" | grep -q "^<<<<<"; then
        log_warning "$branch: CONFLICTS DETECTED"
        CONFLICTS_FOUND=1
        BRANCH_STATUS[$branch]="conflict"
        
        # Show which files have conflicts
        echo "$MERGE_RESULT" | grep -B1 "^<<<<<" | grep -v "^--$" | head -20
    else
        log_success "$branch: Clean merge possible"
        BRANCH_STATUS[$branch]="ready"
    fi
done

echo ""

if [ $CONFLICTS_FOUND -eq 1 ]; then
    log_error "Conflicts detected! Review the conflicts above before proceeding."
    echo ""
    echo "Options:"
    echo "  1. Manually resolve conflicts in the conflicting branches"
    echo "  2. Run with --force to attempt merge anyway (will stop at first conflict)"
    echo "  3. Use --skip-conflicts to merge only non-conflicting branches"
    
    if [ "$3" != "--force" ] && [ "$3" != "--skip-conflicts" ]; then
        exit 1
    fi
fi

echo ""
log_info "Phase 2: Performing merges"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

MERGED_COUNT=0
SKIPPED_COUNT=0

for branch in "${MILESTONE_BRANCHES[@]}"; do
    status="${BRANCH_STATUS[$branch]}"
    
    if [ "$status" = "missing" ]; then
        log_warning "Skipping missing branch: $branch"
        ((SKIPPED_COUNT++))
        continue
    fi
    
    if [ "$status" = "conflict" ] && [ "$3" = "--skip-conflicts" ]; then
        log_warning "Skipping conflicting branch: $branch"
        ((SKIPPED_COUNT++))
        continue
    fi
    
    log_info "Merging: $branch"
    
    # Perform the actual merge
    if git merge --no-ff "$branch" -m "Merge $branch into $TARGET_BRANCH"; then
        log_success "Successfully merged: $branch"
        ((MERGED_COUNT++))
    else
        log_error "Merge failed for: $branch"
        echo "Resolve conflicts manually, then run: git merge --continue"
        exit 1
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_success "Merge orchestration complete!"
echo "  Merged: $MERGED_COUNT branches"
echo "  Skipped: $SKIPPED_COUNT branches"
echo ""
echo "Current branch: $(git branch --show-current)"
echo "Latest commit: $(git log -1 --oneline)"
