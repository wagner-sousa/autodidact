#!/usr/bin/env python3
"""UserPromptSubmit hook: if the previous turn was complex, inject the
skill_manage trigger text so Claude evaluates whether a skill update is due.

Reads the JSON payload from stdin (Claude Code standard), but only cares
about the marker file left by detect_complexity.py — the payload itself is
not needed here.
"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(SCRIPT_DIR, "..", ".state", "pending.json")


def main():
    if not os.path.exists(MARKER):
        return

    try:
        with open(MARKER) as f:
            data = json.load(f)
        tool_count = data.get("tool_call_count", "?")
        tools = ", ".join(data.get("tools_used", [])[:6])
    except (json.JSONDecodeError, ValueError, OSError):
        tool_count, tools = "?", ""

    os.remove(MARKER)

    print(
        "autodidact pending: previous turn had {} tool calls ({}). When you "
        "FINISH this task, apply the autodidact skill: evaluate whether what "
        "was learned deserves a new skill or a patch to an existing one. "
        "PREFER patch. Always ask for approval before writing.".format(
            tool_count, tools
        )
    )


if __name__ == "__main__":
    main()
