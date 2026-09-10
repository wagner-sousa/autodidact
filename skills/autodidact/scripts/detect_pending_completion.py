#!/usr/bin/env python3
"""Stop hook: clear approved pending entries once skill-creator has done its job.

An approved create/patch/edit/write_file entry has no content of its own —
skill-creator writes directly to .claude/skills/<target>/ after approve. This
hook watches for that: if the target skill's files changed (any mtime newer
than the entry's approved_at) since approval, the request is done, so the
pending entry is deleted automatically. Nothing here validates content —
that is skill-creator's and the agent's responsibility, not a deterministic
script's.

delete/remove_file entries never reach this hook — pending.py approve applies
them immediately and removes them itself, no generation involved.
"""
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(SCRIPT_DIR, "..")
PROJECT_SKILLS_ROOT = os.path.join(SKILL_DIR, "..")
USER_SKILLS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "skills")
PENDING_DIR = os.path.join(SKILL_DIR, ".state", "pending")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}


def _skills_root(scope_override=None):
    scope = scope_override or _load_config().get("scope", "project")
    return USER_SKILLS_ROOT if scope == "user" else PROJECT_SKILLS_ROOT


def _skill_mtime(base):
    if not os.path.isdir(base):
        return None
    latest = None
    for root, _dirs, files in os.walk(base):
        for name in files:
            mtime = os.path.getmtime(os.path.join(root, name))
            if latest is None or mtime > latest:
                latest = mtime
    return latest


def _approved_at_epoch(manifest):
    try:
        return time.mktime(time.strptime(manifest["approved_at"], "%Y-%m-%dT%H:%M:%S"))
    except (KeyError, ValueError, TypeError):
        return None


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    if not os.path.isdir(PENDING_DIR):
        return

    cleared = []
    for entry_id in sorted(os.listdir(PENDING_DIR)):
        manifest_path = os.path.join(PENDING_DIR, entry_id, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, ValueError):
            continue

        if manifest.get("action") not in ("create", "patch", "edit", "write_file"):
            continue
        approved_epoch = _approved_at_epoch(manifest)
        if approved_epoch is None:
            continue

        target = manifest.get("target_skill")
        if not target:
            continue
        base = os.path.join(_skills_root(manifest.get("scope")), target)
        latest = _skill_mtime(base)
        if latest is not None and latest >= approved_epoch:
            import shutil
            shutil.rmtree(os.path.join(PENDING_DIR, entry_id), ignore_errors=True)
            cleared.append((entry_id, manifest["action"], target))

    for entry_id, action, target in cleared:
        print(f"autodidact: pending {entry_id} ({action} {target}) cleared — skill-creator finished.")


if __name__ == "__main__":
    main()
