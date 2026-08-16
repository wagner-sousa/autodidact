#!/usr/bin/env bash
# SessionStart hook: surface any autodidact proposals still waiting for
# approval, since they survive restarts (Hermes-style pending queue).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT=$(python3 "$SCRIPT_DIR/pending.py" list)

if [[ -n "$OUTPUT" ]]; then
    echo "autodidact: pending proposals awaiting approval (id / action / target / summary):"
    echo "$OUTPUT"
    echo "Approve with: python3 .claude/skills/autodidact/scripts/pending.py approve <id>"
    echo "Reject with: python3 .claude/skills/autodidact/scripts/pending.py reject <id>"
fi
