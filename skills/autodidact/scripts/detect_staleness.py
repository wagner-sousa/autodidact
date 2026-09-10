#!/usr/bin/env python
"""Stop hook: detect a domain touched this session whose skill exists but was
never invoked — a signal the skill may be missing something (stale/incomplete)
rather than a signal a new skill is needed.

Reads the full session transcript (JSONL at transcript_path from the hook
payload) and collects, across every turn (not just the last one):
  - which skills were explicitly invoked (Skill tool_use blocks)
  - which files were edited (Edit/Write/NotebookEdit tool_use blocks)

Edited file paths are mapped to known domains using the same auto-discovery
as detect_domain_recurrence.py (Integration dir + config known_domains). If a
domain has files edited this session, has an existing skill directory, but
that skill was never invoked via the Skill tool, this script stages a patch
request (pending.py new --action patch --target <domain>) and instructs the
agent to use AskUserQuestion at the end of the current task.

This script never generates skill content and never calls approve — same
division of responsibility as detect_domain_recurrence.py: we only measure
the need for a create/patch, skill-creator does the actual drafting.
"""
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(SCRIPT_DIR, "..")
STATE_DIR = os.path.join(SKILL_DIR, ".state")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
PENDING_DIR = os.path.join(STATE_DIR, "pending")
PENDING_SCRIPT = os.path.join(SCRIPT_DIR, "pending.py")
SKILLS_ROOT = os.path.join(SKILL_DIR, "..")

sys.path.insert(0, SCRIPT_DIR)
from detect_domain_recurrence import (  # noqa: E402
    get_known_domains,
    skill_exists,
)

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}


def get_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH) as f:
            raw = json.load(f)
        return raw.get("domain_recurrence", {})
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def session_activity(transcript_path):
    """Return (invoked_skills, edited_paths) across the whole transcript."""
    invoked_skills = set()
    edited_paths = []

    if not transcript_path or not os.path.exists(transcript_path):
        return invoked_skills, edited_paths

    with open(transcript_path, "r") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        for block in content:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            tool_input = block.get("input", {}) or {}

            if name == "Skill":
                skill_name = tool_input.get("skill")
                if skill_name:
                    invoked_skills.add(skill_name)
            elif name in EDIT_TOOLS:
                path = tool_input.get("file_path") or tool_input.get("notebook_path")
                if path:
                    edited_paths.append(path)

    return invoked_skills, edited_paths


def detect_domains_in_paths(edited_paths, known_domains):
    """Return set of skill_dir_names whose domain pattern matches an edited path."""
    found = set()
    for path in edited_paths:
        path_lower = path.lower()
        for pattern, skill_name in known_domains.items():
            if re.search(pattern, path_lower):
                found.add(skill_name)
    return found


def existing_pending_id(target, action):
    if not os.path.isdir(PENDING_DIR):
        return None
    for entry_id in os.listdir(PENDING_DIR):
        manifest_path = os.path.join(PENDING_DIR, entry_id, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, ValueError):
            continue
        if (
            manifest.get("target_skill") == target
            and manifest.get("action") == action
            and not manifest.get("rejected_at")
        ):
            return entry_id
    return None


def stage_request(target, action):
    try:
        result = subprocess.run(
            [sys.executable or "python3", PENDING_SCRIPT, "new",
             "--action", action, "--target", target],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    transcript_path = payload.get("transcript_path")
    config = get_config()
    known_domains = get_known_domains(config)
    if not known_domains:
        return

    invoked_skills, edited_paths = session_activity(transcript_path)
    if not edited_paths:
        return

    touched_domains = detect_domains_in_paths(edited_paths, known_domains)
    if not touched_domains:
        return

    for domain in touched_domains:
        if not skill_exists(domain):
            continue
        if domain in invoked_skills:
            continue

        entry_id = existing_pending_id(domain, "patch")
        if entry_id is None:
            entry_id = stage_request(domain, "patch")

        if entry_id:
            print(
                "autodidact: files under '{}' were edited this session but its skill "
                "was never invoked via the Skill tool — a patch request is queued "
                "(id {}) in case the skill is missing something. At the END of your "
                "current task/response, use AskUserQuestion to ask: approve (then "
                "invoke skill-creator to patch .claude/skills/{}/), reject, or decide "
                "later. Don't ask mid-task.".format(domain, entry_id, domain)
            )


if __name__ == "__main__":
    main()
