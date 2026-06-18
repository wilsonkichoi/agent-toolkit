#!/bin/bash
set -euo pipefail

REPO="wilsonkichoi/agent-toolkit"
BRANCH="main"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}/bootstrap"

GREEN='\033[32m'
YELLOW='\033[33m'
BLUE='\033[34m'
BOLD='\033[1m'
RESET='\033[0m'

info() { echo -e "${BLUE}==>${RESET} $1"; }
success() { echo -e "${GREEN}✓${RESET} $1"; }
warn() { echo -e "${YELLOW}!${RESET} $1"; }
header() { echo -e "\n${BOLD}$1${RESET}\n"; }

prompt_yn() {
  local msg="$1" default="${2:-y}"
  if [ "$default" = "y" ]; then
    printf "  %s [Y/n]: " "$msg"
  else
    printf "  %s [y/N]: " "$msg"
  fi
  read -r answer
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}

prompt_setting() {
  local key="$1" value="$2" desc="$3"
  local current
  current=$(jq -r ".${key} // empty" ~/.claude/settings.json 2>/dev/null || true)

  echo -e "  ${BOLD}${key}${RESET}: ${desc}"
  if [ -n "$current" ]; then
    echo "    Current: $current"
  fi
  echo "    Recommended: $value"
  printf "    [a]ccept / [s]kip / [o]verride with custom value: "
  read -r choice
  case "$choice" in
    a|A|"")
      echo "$value"
      return 0
      ;;
    o|O)
      printf "    Enter value: "
      read -r custom
      echo "$custom"
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# Check prerequisites
if ! command -v claude &>/dev/null; then
  echo "Error: 'claude' CLI not found in PATH."
  echo "Install Claude Code first: https://docs.anthropic.com/en/docs/claude-code"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "Error: 'jq' not found. Install with: brew install jq"
  exit 1
fi

header "Claude Code Bootstrap - ${REPO}"

# Ensure settings.json exists
mkdir -p ~/.claude
if [ ! -f ~/.claude/settings.json ]; then
  echo '{}' > ~/.claude/settings.json
fi

# --- Step 1: Register this repo as marketplace (prerequisite) ---
header "1. Register marketplace: ${REPO}"
if prompt_yn "Add ${REPO} as marketplace?"; then
  claude plugin marketplace add "$REPO"
  success "Registered ${REPO}"
else
  warn "Skipped. Plugins from this repo won't be installable."
fi

# --- Step 2: Register additional marketplaces ---
header "2. Additional marketplaces"

MARKETPLACES_YAML=$(curl -fsSL "${RAW_BASE}/config/marketplaces.yaml" 2>/dev/null || true)
if [ -z "$MARKETPLACES_YAML" ]; then
  warn "Could not fetch marketplaces.yaml, skipping"
else
  while IFS= read -r repo; do
    desc=$(echo "$MARKETPLACES_YAML" | grep -A1 "repo: ${repo}" | grep "description:" | sed 's/.*description: //')
    if prompt_yn "${repo} - ${desc}"; then
      claude plugin marketplace add "$repo" && success "Registered ${repo}" || warn "Failed: ${repo}"
    fi
  done < <(echo "$MARKETPLACES_YAML" | grep "^- repo:" | sed 's/- repo: //')
fi

# --- Step 3: Install plugins ---
header "3. Install plugins"

PLUGINS_YAML=$(curl -fsSL "${RAW_BASE}/config/plugins.yaml" 2>/dev/null || true)
if [ -z "$PLUGINS_YAML" ]; then
  warn "Could not fetch plugins.yaml, skipping"
else
  INSTALLED=()
  while IFS='|' read -r name marketplace desc; do
    if prompt_yn "${name}@${marketplace} - ${desc}"; then
      if claude plugin install "${name}@${marketplace}" 2>/dev/null; then
        success "Installed ${name}@${marketplace}"
        INSTALLED+=("${name}@${marketplace}")
      else
        warn "Failed to install ${name}@${marketplace}"
      fi
    fi
  done < <(echo "$PLUGINS_YAML" | awk '
    /^- name:/ { name=$NF }
    /marketplace:/ { mp=$NF }
    /description:/ { desc=$0; sub(/.*description: /, "", desc); print name "|" mp "|" desc }
  ')

  # Disable all installed plugins globally
  if [ ${#INSTALLED[@]} -gt 0 ]; then
    header "4. Disabling plugins globally (enable per-project as needed)"
    for plugin in "${INSTALLED[@]}"; do
      claude plugin disable --scope user "$plugin" 2>/dev/null && success "Disabled ${plugin}" || true
    done
  fi
fi

# --- Step 5: Configure settings ---
header "5. Settings"

SETTINGS_YAML=$(curl -fsSL "${RAW_BASE}/config/settings.yaml" 2>/dev/null || true)
if [ -z "$SETTINGS_YAML" ]; then
  warn "Could not fetch settings.yaml, skipping"
else
  while IFS='|' read -r key value desc; do
    result=$(prompt_setting "$key" "$value" "$desc") && {
      tmp=$(mktemp)
      jq --arg k "$key" --arg v "$result" '.[$k] = $v' ~/.claude/settings.json > "$tmp" && mv "$tmp" ~/.claude/settings.json
      success "Set ${key} = ${result}"
    } || true
  done < <(echo "$SETTINGS_YAML" | awk '
    /^- key:/ { key=$NF }
    /value:/ { val=$NF }
    /description:/ { desc=$0; sub(/.*description: /, "", desc); print key "|" val "|" desc }
  ')
fi

# --- Step 6: Statusline ---
header "6. Status line"
echo "  Custom statusline shows: directory (branch), model, context usage bar, cost"
if prompt_yn "Install statusline?"; then
  STATUSLINE=$(curl -fsSL "${RAW_BASE}/scripts/statusline.sh" 2>/dev/null || true)
  if [ -n "$STATUSLINE" ]; then
    echo "$STATUSLINE" > ~/.claude/statusline.sh
    chmod +x ~/.claude/statusline.sh
    tmp=$(mktemp)
    jq '.statusLine = {"type": "command", "command": "~/.claude/statusline.sh"}' ~/.claude/settings.json > "$tmp" && mv "$tmp" ~/.claude/settings.json
    success "Statusline installed"
  else
    warn "Could not fetch statusline.sh"
  fi
fi

# --- Summary ---
header "Done!"
info "Plugins are installed but disabled globally."
info "Enable per-project with: claude plugin enable <name>@<marketplace>"
info "Or enable in .claude/settings.local.json for specific projects."
