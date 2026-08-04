#!/usr/bin/env bash
# pretooluse-guard.sh — Claude Code PreToolUse dispatcher.
#
# Reads the hook JSON on stdin, routes to the right guard, and BLOCKS the tool
# (exit 2) when a guard objects. Reuses the existing guard scripts unchanged:
# it materialises the *content that would be written* into a temp file and hands
# that to the guard, then maps the guard's exit-1 to the hook's block code (2).
#
# Wire via ~/.claude/settings.json (.hooks.PreToolUse) or a plugin hooks.json:
#   matcher "Write|Edit" -> this script.
set -euo pipefail

GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/guards" && pwd)"

INPUT="$(cat)"
tool="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')"

case "$tool" in
  Write|Edit)
    file="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"
    # Content about to be written: Write.content, or Edit.new_string (the added text).
    content="$(printf '%s' "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // empty')"
    [ -n "$content" ] || exit 0

    # Preserve the real extension so the guard's skip-by-type logic still applies.
    ext="${file##*.}"
    [ "$ext" = "$file" ] && ext="txt"
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' EXIT
    tmpf="$tmpdir/content.$ext"
    printf '%s' "$content" > "$tmpf"

    if ! msg="$(bash "$GUARD_DIR/secrets-guard.sh" "$tmpf" 2>&1)"; then
      # Re-point the guard's temp-file path back to the real target in the message.
      printf '%s\n' "${msg//$tmpf/$file}" >&2
      echo "🚫 pretooluse-guard: blocked write to $file (possible secret)." >&2
      exit 2
    fi
    ;;
esac

exit 0
