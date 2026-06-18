#!/bin/bash
input=$(cat)

# If in a worktree, use the original_cwd instead of current_dir
WORKTREE_NAME=$(echo "$input" | jq -r '.worktree.name // empty')
if [ -n "$WORKTREE_NAME" ]; then
  DIR=$(echo "$input" | jq -r '.worktree.original_cwd')
  DIR_DISPLAY="${DIR} (${WORKTREE_NAME})"
else
  DIR=$(echo "$input" | jq -r '.workspace.current_dir')
  # Get git branch for non-worktree sessions
  BRANCH=$(cd "$DIR" 2>/dev/null && git rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ -n "$BRANCH" ]; then
    DIR_DISPLAY="${DIR} (${BRANCH})"
  else
    DIR_DISPLAY="${DIR}"
  fi
fi

MODEL=$(echo "$input" | jq -r '.model.display_name')
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)

# Format cost to 2 decimal places
COST=$(printf '%.2f' "$COST")

# Color based on usage: green < 50%, yellow 50-80%, red > 80%
if [ "$PCT" -ge 80 ]; then
  COLOR='\033[31m'
elif [ "$PCT" -ge 50 ]; then
  COLOR='\033[33m'
else
  COLOR='\033[32m'
fi
RESET='\033[0m'

# Build progress bar
BAR_WIDTH=20
FILLED=$((PCT * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
[ "$FILLED" -gt 0 ] && BAR=$(printf "%${FILLED}s" | tr ' ' '▓')
[ "$EMPTY" -gt 0 ] && BAR="${BAR}$(printf "%${EMPTY}s" | tr ' ' '░')"

echo -e "${DIR_DISPLAY} | [$MODEL] ${COLOR}${BAR} ${PCT}%${RESET} | \$${COST}"
