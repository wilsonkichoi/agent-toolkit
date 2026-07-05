#!/bin/bash
set -euo pipefail

REPO="wilsonkichoi/agent-toolkit"
BRANCH="main"
RAW_BASE="https://raw.githubusercontent.com/${REPO}/${BRANCH}/bootstrap"

# Detect if running from local clone or via curl
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/config/repos.yaml" ]; then
  LOCAL_BASE="${SCRIPT_DIR}"
else
  LOCAL_BASE=""
fi

# Read file: local clone first, fall back to curl (for when repo goes public)
read_config() {
  local path="$1"
  if [ -n "$LOCAL_BASE" ] && [ -f "${LOCAL_BASE}/${path}" ]; then
    cat "${LOCAL_BASE}/${path}"
  else
    curl -fsSL "${RAW_BASE}/${path}" 2>/dev/null || true
  fi
}

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
  read -r answer </dev/tty
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}

prompt_setting() {
  local key="$1" value="$2" desc="$3"
  local current
  current=$(jq -r ".${key} // empty" ~/.claude/settings.json 2>/dev/null || true)

  echo -e "  ${BOLD}${key}${RESET}: ${desc}" >&2
  if [ -n "$current" ]; then
    echo "    Current: $current" >&2
  fi
  echo "    Recommended: $value" >&2
  printf "    [a]ccept / [s]kip / [o]verride with custom value: " >&2
  read -r choice </dev/tty
  case "$choice" in
    a|A|"")
      echo "$value"
      return 0
      ;;
    o|O)
      printf "    Enter value: " >&2
      read -r custom </dev/tty
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

# --- Step 1: Register repos ---
header "1. Register repos"

REPOS_YAML=$(read_config "config/repos.yaml")
if [ -z "$REPOS_YAML" ]; then
  warn "Could not fetch repos.yaml, skipping"
else
  while IFS= read -r repo; do
    desc=$(echo "$REPOS_YAML" | awk -v r="$repo" '
      $0 == "- repo: " r { found=1; next }
      found && /^[[:space:]]+description:/ { sub(/.*description: /, ""); print; exit }
      found && /^- repo:/ { exit }
    ')
    if prompt_yn "${repo} - ${desc}"; then
      claude plugin marketplace add "$repo" && success "Registered ${repo}" || warn "Failed: ${repo}"
    fi
  done < <(echo "$REPOS_YAML" | grep "^- repo:" | sed 's/- repo: //')
fi

# --- Step 2: Install plugins ---
header "2. Install plugins"

PLUGINS_YAML=$(read_config "config/plugins.yaml")
if [ -z "$PLUGINS_YAML" ]; then
  warn "Could not fetch plugins.yaml, skipping"
else
  # Detect already-installed plugins (user scope only)
  info "Checking installed plugins..."
  INSTALLED_PLUGIN_IDS=""
  if INSTALLED_PLUGINS_JSON=$(claude plugin list --json 2>/dev/null); then
    INSTALLED_PLUGIN_IDS=$(echo "$INSTALLED_PLUGINS_JSON" | jq -r '.[] | select(.scope == "user") | .id' 2>/dev/null | sort -u)
  fi

  is_plugin_installed() {
    [ -n "$INSTALLED_PLUGIN_IDS" ] && echo "$INSTALLED_PLUGIN_IDS" | grep -qx "$1"
  }

  # Refresh marketplace caches if there are existing installs to update
  if [ -n "$INSTALLED_PLUGIN_IDS" ]; then
    info "Refreshing marketplace caches..."
    while IFS= read -r mp; do
      claude plugin marketplace update "$mp" 2>/dev/null || true
    done < <(echo "$PLUGINS_YAML" | grep -E "^[[:space:]]+marketplace:" | awk '{print $NF}' | sort -u)
  fi

  INSTALLED=()
  while IFS='|' read -r name marketplace desc; do
    plugin_id="${name}@${marketplace}"

    if is_plugin_installed "$plugin_id"; then
      info "${plugin_id} already installed"
      if prompt_yn "  Update?" "n"; then
        if claude plugin update -s user "$plugin_id" 2>/dev/null; then
          success "Updated ${plugin_id}"
          INSTALLED+=("$plugin_id")
        else
          warn "Failed to update ${plugin_id}"
        fi
      else
        info "Skipped"
      fi
    else
      if prompt_yn "${plugin_id} - ${desc}"; then
        if claude plugin install "$plugin_id" 2>/dev/null; then
          success "Installed ${plugin_id}"
          INSTALLED+=("$plugin_id")
        else
          warn "Failed to install ${plugin_id}"
        fi
      fi
    fi
  done < <(echo "$PLUGINS_YAML" | awk '
    /^- name:/ { name=$NF }
    /^[[:space:]]+marketplace:/ { mp=$NF }
    /^[[:space:]]+description:/ { desc=$0; sub(/.*description: /, "", desc); print name "|" mp "|" desc }
  ')

  # Disable all installed plugins globally
  if [ ${#INSTALLED[@]} -gt 0 ]; then
    header "3. Disabling plugins globally (enable per-project as needed)"
    for plugin in "${INSTALLED[@]}"; do
      claude plugin disable --scope user "$plugin" 2>/dev/null && success "Disabled ${plugin}" || true
    done
  fi
fi

# --- Step 4: Configure settings ---
header "4. Settings"

SETTINGS_YAML=$(read_config "config/settings.yaml")
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
    /^[[:space:]]+value:/ { val=$NF }
    /^[[:space:]]+description:/ { desc=$0; sub(/.*description: /, "", desc); print key "|" val "|" desc }
  ')
fi

# --- Step 5: Statusline ---
header "5. Status line"
echo "  Custom statusline shows: directory (branch), model, context usage bar, cost"
if prompt_yn "Install statusline?"; then
  STATUSLINE=$(read_config "scripts/statusline.sh")
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
