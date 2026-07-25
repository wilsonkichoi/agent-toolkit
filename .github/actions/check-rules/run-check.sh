#!/usr/bin/env bash
# Entry point for the check-rules composite action.
#
# The action vendors no checker. It runs the copy of
# plugins/dev/scripts/resolve_project_rules.py that shipped with this action's own checkout,
# so the contract CI enforces is always the one the dev plugin implements. The caller's
# repository supplies only the directory to check.
#
# Every input arrives through the environment. That keeps action.yml's `run:` bodies free of
# `${{ }}` interpolation and lets tools/test_check_rules_action.py drive this script directly
# against fixtures instead of only through a GitHub runner.

set -euo pipefail
# An inherited CDPATH makes `cd` echo its destination, which would corrupt every path this
# script captures from a subshell.
unset CDPATH

CONFIG_RELATIVE_PATH=".agent-toolkit/dev.md"
CHECKER_RELATIVE_PATH="plugins/dev/scripts/resolve_project_rules.py"

script_dir="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
action_root="$(cd -P -- "${script_dir}/../../.." && pwd)"

die() {
  echo "check-rules: $*" >&2
  exit 1
}

emit() {
  local name="$1" value="$2"
  [ -n "${GITHUB_OUTPUT:-}" ] || return 0
  printf '%s=%s\n' "$name" "$value" >>"$GITHUB_OUTPUT"
}

emit_multiline() {
  local name="$1" value="$2"
  local delimiter="CHECK_RULES_EOF_$$_${RANDOM}"
  [ -n "${GITHUB_OUTPUT:-}" ] || return 0
  case "$value" in
    *"$delimiter"*) die "generated output delimiter collides with the report body" ;;
  esac
  {
    printf '%s<<%s\n' "$name" "$delimiter"
    printf '%s\n' "$value"
    printf '%s\n' "$delimiter"
  } >>"$GITHUB_OUTPUT"
}

resolve_target() {
  local target="${CHECK_RULES_TARGET:-}"
  [ -n "$target" ] || die "CHECK_RULES_TARGET is required"
  [ -d "$target" ] || die "the path input does not name a directory: ${target}"
  (cd -P -- "$target" && pwd)
}

detect() {
  local target
  target="$(resolve_target)"
  if [ -f "${target}/${CONFIG_RELATIVE_PATH}" ]; then
    emit config present
  else
    emit config absent
  fi
}

check() {
  local target config checker workdir stdout_file stderr_file report status
  target="$(resolve_target)"
  config="${CHECK_RULES_CONFIG:-}"
  if [ -z "$config" ]; then
    if [ -f "${target}/${CONFIG_RELATIVE_PATH}" ]; then
      config=present
    else
      config=absent
    fi
  fi

  if [ "$config" = absent ]; then
    report="check-rules: skipped ${target}: no ${CONFIG_RELATIVE_PATH}, so the dev plugin's rules contract does not apply to this repository."
    printf '%s\n' "$report"
    emit result skipped
    emit status 0
    emit_multiline report "$report"
    return 0
  fi
  [ "$config" = present ] || die "unexpected configuration state: ${config}"

  checker="${action_root}/${CHECKER_RELATIVE_PATH}"
  [ -f "$checker" ] ||
    die "the installed action copy of ${CHECKER_RELATIVE_PATH} is missing at ${checker}"
  command -v uv >/dev/null 2>&1 ||
    die "uv is not on PATH; the action installs it before this step"

  workdir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/check-rules.XXXXXX")"
  stdout_file="${workdir}/stdout"
  stderr_file="${workdir}/stderr"
  status=0
  # Run from a scratch directory with project discovery disabled, so checking a repository
  # never creates an environment or lockfile inside it.
  (cd -- "$workdir" && uv run --no-project --script "$checker" --check "$target") \
    >"$stdout_file" 2>"$stderr_file" || status=$?
  # Replay the checker's streams unchanged: this action reports its verdict, it never
  # rewrites the diagnostics that justify it.
  cat -- "$stdout_file"
  cat -- "$stderr_file" >&2
  report="$(cat -- "$stdout_file" "$stderr_file")"
  rm -rf -- "$workdir"

  emit result checked
  emit status "$status"
  emit_multiline report "$report"
  return 0
}

verdict() {
  local status="${CHECK_RULES_STATUS:-}"
  case "$status" in
    '' | *[!0-9]*)
      die "CHECK_RULES_STATUS must be a non-negative integer, got '${status}'"
      ;;
  esac
  [ "$status" != 0 ] || return 0
  echo "check-rules: the rules contract check failed with exit status ${status};" \
    "the checker diagnostics above are unmodified." >&2
  exit "$status"
}

case "${1:-}" in
  detect) detect ;;
  check) check ;;
  verdict) verdict ;;
  *) die "usage: run-check.sh <detect|check|verdict>" ;;
esac
