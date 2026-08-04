#!/usr/bin/env bash
# secrets-guard.sh — blocks writes containing common secret patterns.
# Wired as a Claude Code PreToolUse hook on Write/Edit.
# Zero prompt cost: runs before Claude sees the file content.

set -euo pipefail

# Patterns that indicate a secret
PATTERNS=(
  'PRIVATE KEY'              # PEM private keys
  'BEGIN RSA PRIVATE'
  'BEGIN EC PRIVATE'
  'sk-[a-zA-Z0-9]{20,}'     # OpenAI / Anthropic secret keys
  'ghp_[a-zA-Z0-9]{36}'     # GitHub PATs (classic)
  'github_pat_[a-zA-Z0-9_]{82}' # GitHub fine-grained PATs
  'xoxb-[0-9]+-[a-zA-Z0-9-]+' # Slack bot tokens
  'xoxp-[0-9]+-[a-zA-Z0-9-]+' # Slack user tokens
  'AKIA[0-9A-Z]{16}'         # AWS access key IDs
  'aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}'
  'password\s*=\s*["\x27][^"\x27]{8,}'
  'passwd\s*=\s*["\x27][^"\x27]{8,}'
  'secret\s*=\s*["\x27][^"\x27]{8,}'
  'api_key\s*=\s*["\x27][A-Za-z0-9_\-]{16,}'
  'Bearer\s+[A-Za-z0-9._\-]{20,}' # Bearer tokens in source
)

FILE="${1:-}"
if [[ -z "$FILE" ]]; then
  echo "secrets-guard: no file argument — skipping" >&2
  exit 0
fi

# Skip binary files, lock files, and known safe paths
if [[ "$FILE" =~ \.(png|jpg|jpeg|gif|ico|woff|woff2|ttf|eot|svg|pdf|zip|tar|gz|lock)$ ]]; then
  exit 0
fi
if [[ "$FILE" =~ (uv\.lock|package-lock\.json|yarn\.lock|Gemfile\.lock)$ ]]; then
  exit 0
fi

FOUND=0
for pattern in "${PATTERNS[@]}"; do
  # A line matching a secret pattern is exempt if it carries an inline `# nosec`
  # marker. Flag only when at least one matching line is NOT annotated nosec.
  if grep -iE "$pattern" "$FILE" 2>/dev/null | grep -qivE 'nosec'; then
    echo "🚫 secrets-guard: possible secret in $FILE (matched: $pattern)" >&2
    FOUND=1
  fi
done

if [[ $FOUND -eq 1 ]]; then
  echo "" >&2
  echo "  Move secrets to environment variables or a .env file (never committed)." >&2
  echo "  If this is a false positive, add an inline exception comment: # nosec" >&2
  exit 1
fi

exit 0
