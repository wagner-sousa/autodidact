#!/usr/bin/env python
"""Stop hook: print unconditional skill-capture reminder and conditionally
write a complexity marker for the next turn.

Always prints a reminder covering the four capture-worthy criteria (a-d),
including cases the tool-count check can't see (user correction, dead end
contornado, non-obvious discovery). When the turn also crosses the
configured tool-call threshold, writes .state/pending.json so that
inject_reminder.py injects a richer count-based nudge at the start of the
next turn.
"""
import json
import os
import sys

SKILL_DIR = os.path.join(os.path.dirname(__file__), "..")
STATE_DIR = os.path.join(SKILL_DIR, ".state")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
DEFAULT_TRIGGER = {
    "min_tool_calls": 5,
    "min_file_edits": 2,
    "readonly_threshold": 12,
}
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
READ_TOOLS = {"Read"}


def get_trigger_config():
    """Precedence: SKILL_MANAGE_THRESHOLD env var (overrides min_tool_calls only) > config.json["trigger"] > defaults."""
    trigger = dict(DEFAULT_TRIGGER)

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            trigger.update(cfg.get("trigger", {}))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    env_value = os.environ.get("SKILL_MANAGE_THRESHOLD")
    if env_value:
        try:
            trigger["min_tool_calls"] = int(env_value)
        except ValueError:
            pass

    return trigger


def should_fire(count, edit_count, trigger):
    """Two independent paths, mirroring self-improving-skills' tool-calls vs
    readonly split: an edit-heavy turn fires on a lower bar than a pure
    read/investigation turn, which needs more evidence before proposing."""
    if edit_count >= trigger["min_file_edits"] and count >= trigger["min_tool_calls"]:
        return True
    if edit_count == 0 and count >= trigger["readonly_threshold"]:
        return True
    return False


def last_turn_tool_calls(transcript_path):
    """Count tool_use blocks emitted since the last user message."""
    if not transcript_path or not os.path.exists(transcript_path):
        return 0, []

    tool_names = []

    with open(transcript_path, "r") as f:
        lines = f.readlines()

    # Walk backwards until we cross a user (non-tool-result) message —
    # that marks the start of the current turn.
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = entry.get("message", {})
        role = msg.get("role")

        if role == "user":
            content = msg.get("content", "")
            is_tool_result = isinstance(content, list) and any(
                block.get("type") == "tool_result" for block in content
            )
            if not is_tool_result:
                break

        if role == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_use":
                        tool_names.append(block.get("name", "?"))

    return len(tool_names), tool_names


def build_reminder(count, edit_count, read_count, trigger):
    """English, dynamic reminder — reports this turn's actual counts plus the
    configured thresholds, instead of a hardcoded number that can drift out
    of sync with config.json."""
    return (
        "autodidact: when you finish, evaluate whether this turn is worth "
        "capturing as a new skill or a patch to an existing one. This turn: "
        f"{count} tool call(s), {edit_count} file edit(s) (Edit/Write/NotebookEdit), "
        f"{read_count} file read(s). Configured thresholds (config.json trigger): "
        f"min_tool_calls={trigger['min_tool_calls']}, min_file_edits={trigger['min_file_edits']}, "
        f"readonly_threshold={trigger['readonly_threshold']}. Criteria: (a) tool-call "
        "volume crossed the threshold above, (b) an error or dead end you worked "
        "around, (c) the user corrected your approach, or (d) a non-obvious flow "
        "you discovered. If any apply, propose via pending.py new. Prefer patch "
        "over create. Always queue, never write directly."
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    transcript_path = payload.get("transcript_path")
    count, tool_names = last_turn_tool_calls(transcript_path)
    edit_count = sum(1 for name in tool_names if name in EDIT_TOOLS)
    read_count = sum(1 for name in tool_names if name in READ_TOOLS)
    trigger = get_trigger_config()

    # Unconditional: covers turns whose value isn't measured by tool-call
    # volume (a corrected approach, a dead end worked around, a non-obvious
    # discovery) — cases the count-based trigger below structurally can't see.
    print(build_reminder(count, edit_count, read_count, trigger))

    if not should_fire(count, edit_count, trigger):
        return

    os.makedirs(STATE_DIR, exist_ok=True)
    marker_path = os.path.join(STATE_DIR, "pending.json")
    with open(marker_path, "w") as f:
        json.dump(
            {
                "tool_call_count": count,
                "edit_count": edit_count,
                "tools_used": tool_names,
            },
            f,
        )


if __name__ == "__main__":
    main()
