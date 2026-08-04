#!/usr/bin/env bash
# commit-guard.sh — enforces Conventional Commits format and branch naming.
# Wired as a git commit-msg hook AND as a Claude Code PreToolUse hook on Bash(git commit*).

set -euo pipefail

COMMIT_MSG_FILE="${1:-}"

# ── 1. Branch name check ─────────────────────────────────────────────────────

BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "HEAD")

# Allow main, develop, and release branches
if [[ "$BRANCH" =~ ^(main|master|develop|release/.+|hotfix/.+)$ ]]; then
  : # ok
elif [[ ! "$BRANCH" =~ ^(feat|fix|chore|test|docs|refactor)/IS-[0-9]+-[a-z0-9-]+$ ]]; then
  echo "🚫 commit-guard: branch name '$BRANCH' does not follow the required format." >&2
  echo "" >&2
  echo "  Required: type/IS-NNN-short-description" >&2
  echo "  Example:  feat/IS-42-add-review-skill" >&2
  echo "" >&2
  echo "  Rename with: git branch -m <new-name>" >&2
  exit 1
fi

# ── 2. Commit message check ───────────────────────────────────────────────────

if [[ -z "$COMMIT_MSG_FILE" ]]; then
  # Called as a Claude hook, not git hook — nothing to check
  exit 0
fi

MSG=$(cat "$COMMIT_MSG_FILE")

# Strip comments
MSG_STRIPPED=$(echo "$MSG" | grep -v '^#' | head -1)

# ── 2a. Git-generated subjects are exempt ────────────────────────────────────
#
# `git merge` and `git revert` write their own subjects — "Merge branch 'x' into
# y", "Merge remote-tracking branch 'origin/main' into z", 'Revert "feat(a): b"'
# — and none of them can ever be Conventional. Because the house rules forbid
# --no-verify, enforcing the format on those messages leaves no clean way to run
# a local merge or revert at all.
#
# The exemption deliberately covers the ticket-ref check in section 3 too, not
# just the format check. Branch names carry IS-NNN by convention, so EVERY merge
# subject git writes ("Merge branch 'fix/IS-21-guard' into main") contains what
# section 3 reads as a ticket ref; exempting only the format would still block
# the merge on the next rule down.
#
# `Revert ` gets the same treatment as `Merge `. Conventional Commits does
# define a `revert:` type, so a human *can* hand-write a conforming revert — but
# `git revert` does not, and the friction is identical to the merge case: every
# revert would need its generated message rewritten by hand. The line drawn here
# is "git wrote this subject, not a human", and `git revert` sits on git's side.
#
# The match is anchored and case-sensitive, so only git's exact wording
# qualifies: a hand-written "merge the two configs" or "Merged branch main" is
# still held to the Conventional Commits format.
GIT_GENERATED_SUBJECT='^(Merge|Revert) '

if [[ "$MSG_STRIPPED" =~ $GIT_GENERATED_SUBJECT ]]; then
  exit 0
fi

# Conventional Commits: type(optional-scope): description
CC_PATTERN='^(feat|fix|chore|test|docs|refactor|perf|build|ci|revert)(\([a-z0-9_-]+\))?: .{1,100}$'

if ! echo "$MSG_STRIPPED" | grep -qE "$CC_PATTERN"; then
  echo "🚫 commit-guard: commit message does not follow Conventional Commits." >&2
  echo "" >&2
  echo "  Required: type(scope): short description" >&2
  echo "  Types:    feat | fix | chore | test | docs | refactor | perf | build | ci | revert" >&2
  echo "  Examples:" >&2
  echo "    feat(review): add haiku escalation logic" >&2
  echo "    fix: correct secrets-guard regex for AWS keys" >&2
  echo "    chore(deps): bump pre-commit hooks to latest" >&2
  echo "" >&2
  echo "  Your message: $MSG_STRIPPED" >&2
  exit 1
fi

# ── 3. No ticket refs in code ────────────────────────────────────────────────
# (Tickets are only allowed in the PR body via Fixes #N, not in commit messages)
# Allow "Fixes #N" / "Closes #N" in the footer but not PROJ-NNN style refs.
#
# A Jira key — uppercase letters, dash, digits — has exactly the same shape as
# half the standards catalogue (ISO-8601, RFC-7231, SHA-256, CVE-2024-1234), so
# structure alone cannot tell the two apart. Two narrowing rules do it between
# them:
#
#   1. Match case-SENSITIVELY. This rule used to carry `grep -i`, which made it
#      fire on any 2–10 letter word followed by dash-digits in ANY case:
#      node-20, python-3, base-64, bash-3 were all unlandable. Jira keys are
#      canonically uppercase, so requiring uppercase drops that whole class at
#      zero maintenance cost. Known and accepted gap: a lowercase "is-42" now
#      passes — nobody writes ticket refs that way, and "is-*" is a real npm
#      package family we would rather not block.
#   2. Allowlist the standards prefixes that survive rule 1. Standards bodies
#      move slowly, so this list is short and rarely needs touching; when a
#      genuine standard trips the guard, add its prefix here.
#
# Everything left after both rules is a real ticket ref (IS-42, PROJ-123) and is
# reported by name so the author can see what tripped it.

STANDARDS_PREFIXES='ISO|IEC|IEEE|ANSI|RFC|BCP|STD|UTF|UCS|ASCII|SHA|AES|RSA'
STANDARDS_PREFIXES="$STANDARDS_PREFIXES|CVE|CWE|HTTP|TLS|SSL|SSE|AVX|PEP|WCAG"
STANDARDS_PREFIXES="$STANDARDS_PREFIXES|ECMA|JPEG|MPEG|USB|PCI|POSIX|UTC|GMT"

TICKET_REFS=$(echo "$MSG" \
  | grep -oE '\b[A-Z]{2,10}-[0-9]+\b' \
  | grep -vE "^($STANDARDS_PREFIXES)-" || true)

if [[ -n "$TICKET_REFS" ]]; then
  echo "🚫 commit-guard: Jira-style ticket ref found in commit message: $(echo "$TICKET_REFS" | tr '\n' ' ')" >&2
  echo "   Ticket refs belong in CHANGELOG.md only." >&2
  echo "   To link a PR to an Issue, use 'Fixes #N' in the PR body, not the commit." >&2
  echo "   If this is a standards identifier, add its prefix to STANDARDS_PREFIXES." >&2
  exit 1
fi

exit 0
