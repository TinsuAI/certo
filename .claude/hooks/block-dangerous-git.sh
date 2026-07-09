#!/bin/bash

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command')

# Hard-blocked: destructive / irreversible. No confirmation is offered.
# Checked FIRST so `git push --force` blocks instead of falling through to ask.
BLOCK_PATTERNS=(
  "git reset --hard"
  "reset --hard"
  "git clean -fd"
  "git clean -f"
  "git branch -D"
  "git checkout \."
  "git restore \."
  "push --force"
  "push -f"
)

# Confirm-first: recoverable, but outward-facing. Anything that reaches the remote —
# or lands code on `main`, which triggers the prod CD pipeline — must never run
# unattended. The user approves each one.
ASK_PATTERNS=(
  "git push"
  "gh pr merge"
)

for pattern in "${BLOCK_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern"; then
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented you from doing this." >&2
    exit 2
  fi
done

for pattern in "${ASK_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern"; then
    jq -n --arg reason "Confirm: '$COMMAND'. It reaches the remote; landing on main triggers the prod CD pipeline." '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "ask",
        permissionDecisionReason: $reason
      }
    }'
    exit 0
  fi
done

exit 0
