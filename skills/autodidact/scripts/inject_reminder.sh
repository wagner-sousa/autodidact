#!/usr/bin/env bash
# UserPromptSubmit hook: if the previous turn was complex, inject the
# skill_manage trigger text so Claude evaluates whether a skill update is due.
# Reads the JSON payload from stdin (Claude Code standard), but only cares about
# the marker file — the payload itself is not needed here.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKER="$SCRIPT_DIR/../.state/pending.json"

if [[ ! -f "$MARKER" ]]; then
    exit 0
fi

TOOL_COUNT=$(python3 -c "import json,sys; d=json.load(open('$MARKER')); print(d['tool_call_count'])" 2>/dev/null || echo "?")
TOOLS=$(python3 -c "import json,sys; d=json.load(open('$MARKER')); print(', '.join(d['tools_used'][:6]))" 2>/dev/null || echo "")

rm -f "$MARKER"

cat <<EOF
autodidact pending: previous turn had ${TOOL_COUNT} tool calls (${TOOLS}). When you FINISH this task, apply the autodidact skill: evaluate whether what was learned deserves a new skill or a patch to an existing one. PREFER patch. Always ask for approval before writing.
EOF
