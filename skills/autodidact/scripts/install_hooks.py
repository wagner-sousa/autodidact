#!/usr/bin/env python3
"""
Install autodidact hooks into .claude/settings.json (project) or
~/.claude/settings.json (user).
Idempotent: skips any hook whose script name is already present in the event.

Usage:
  python3 .claude/skills/autodidact/scripts/install_hooks.py [--check] [--user]
  --check   only report status, do not write
  --user    install to ~/.claude/settings.json instead of project settings
"""
import json
import os
import sys

def _required_hooks(user_level):
    """Hook entries to install, keyed by event name.

    Hooks always run with the project directory as cwd, regardless of where
    settings.json lives. A user-level install (scope: user) needs an absolute
    path to ~/.claude/skills/autodidact/scripts — a relative .claude/... path
    would resolve against the wrong project and fail.
    """
    if user_level:
        skill_dir = os.path.expanduser("~/.claude/skills/autodidact/scripts")
    else:
        skill_dir = ".claude/skills/autodidact/scripts"
    return {
        "Stop": [
            f"python3 {skill_dir}/detect_complexity.py",
        ],
        "UserPromptSubmit": [
            f"bash {skill_dir}/inject_reminder.sh",
            f"python3 {skill_dir}/detect_domain_recurrence.py",
        ],
        "SessionStart": [
            f"bash {skill_dir}/list_pending.sh",
        ],
    }


def _find_settings(user_level=False):
    if user_level:
        return os.path.expanduser("~/.claude/settings.json")
    # Walk up from cwd looking for .claude/settings.json
    cwd = os.getcwd()
    candidate = os.path.join(cwd, ".claude", "settings.json")
    if os.path.exists(candidate):
        return candidate
    # Fallback: relative to this script (3 levels up to .claude/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.normpath(os.path.join(script_dir, "../../../settings.json"))
    return candidate


def _script_names_in_event(event_cfg):
    """Return basenames of all script commands already wired for an event."""
    names = set()
    for group in event_cfg:
        for hook in group.get("hooks", []):
            if hook.get("type") == "command":
                # strip any prefix (absolute path, env vars, etc.)
                parts = hook["command"].split()
                for part in parts:
                    clean = part.strip("'\"")
                    if clean.endswith(".py") or clean.endswith(".sh"):
                        names.add(os.path.basename(clean))
    return names


def check_installed(settings, user_level=False):
    """Return dict of event -> [missing commands] (empty = fully installed)."""
    hooks_cfg = settings.get("hooks", {})
    missing = {}
    for event, cmds in _required_hooks(user_level).items():
        present_names = _script_names_in_event(hooks_cfg.get(event, []))
        not_found = [
            c for c in cmds
            if os.path.basename(c.split()[-1]) not in present_names
        ]
        if not_found:
            missing[event] = not_found
    return missing


def install(settings, missing):
    hooks_cfg = settings.setdefault("hooks", {})
    for event, cmds in missing.items():
        event_list = hooks_cfg.setdefault(event, [])
        new_entries = [{"type": "command", "command": c} for c in cmds]
        event_list.append({"hooks": new_entries})
    return settings


def main():
    check_only = "--check" in sys.argv
    user_level = "--user" in sys.argv

    settings_path = _find_settings(user_level=user_level)
    level_label = "usuario (~/.claude)" if user_level else "projeto (.claude)"
    print(f"Nivel: {level_label} -> {settings_path}")

    if not os.path.exists(settings_path):
        if check_only:
            print(f"settings.json not found at {settings_path}")
            sys.exit(1)
        print(f"settings.json not found at {settings_path} — will create.")
        settings = {}
    else:
        with open(settings_path) as f:
            settings = json.load(f)

    missing = check_installed(settings, user_level=user_level)

    if not missing:
        print("autodidact hooks already installed - nothing to do.")
        return

    print("Hooks ausentes:")
    for event, cmds in missing.items():
        for c in cmds:
            print(f"  [{event}] {c}")

    if check_only:
        print("\nExecute sem --check para instalar.")
        sys.exit(1)

    updated = install(settings, missing)

    with open(settings_path, "w") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nHooks instalados em {settings_path}")


if __name__ == "__main__":
    main()
