#!/usr/bin/env python
"""autodidact pending queue — a request/approval gate, not a content stage.

A pending entry only records THAT a skill creation/update is wanted — it
never carries the skill's content. Content generation is entirely
skill-creator's job, and it happens AFTER approve, writing straight to
.claude/skills/<target>/ instead of into this queue.

Flow:
  1. pending.py new --action create --target <name>   (records the request)
  2. user reviews, runs pending.py approve <id> whenever ready
  3. approve stamps the entry "approved" and tells the agent to invoke
     skill-creator now for that target/action
  4. skill-creator writes the skill directly to .claude/skills/<target>/
  5. the detect_pending_completion.py Stop hook notices the target's files
     changed since approval and deletes the pending entry automatically

delete/remove_file need no generation, so approve applies them immediately
and clears the entry itself, no hook involved.

Usage:
  pending.py new --action create|patch|edit|delete|write_file|remove_file \
                  --target <skill-name> [--scope project|user] \
                  [--path <relative-path>]   # required for remove_file
  pending.py list
  pending.py show <id>
  pending.py approve <id>
  pending.py reject <id>
"""
import argparse
import json
import os
import shutil
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(SCRIPT_DIR, "..")
PROJECT_SKILLS_ROOT = os.path.join(SKILL_DIR, "..")
USER_SKILLS_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "skills")
PENDING_DIR = os.path.join(SKILL_DIR, ".state", "pending")
MENTIONS_PATH = os.path.join(SKILL_DIR, ".state", "domain_mentions.json")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")

GENERATED_ACTIONS = ("create", "patch", "edit", "write_file")
MECHANICAL_ACTIONS = ("delete", "remove_file")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _skills_root(scope_override=None):
    scope = scope_override or _load_config().get("scope", "project")
    return USER_SKILLS_ROOT if scope == "user" else PROJECT_SKILLS_ROOT


def _load_manifest(entry_id):
    manifest_path = os.path.join(PENDING_DIR, entry_id, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"no pending entry: {entry_id}", file=sys.stderr)
        sys.exit(1)
    with open(manifest_path) as f:
        return manifest_path, json.load(f)


def _save_manifest(manifest_path, manifest):
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def cmd_new(args):
    if args.action == "remove_file" and not args.path:
        print("pending.py new: --path is required for remove_file", file=sys.stderr)
        sys.exit(1)
    if args.action not in MECHANICAL_ACTIONS and not args.target:
        print("pending.py new: --target is required for this action", file=sys.stderr)
        sys.exit(1)

    os.makedirs(PENDING_DIR, exist_ok=True)
    entry_id = str(int(time.time() * 1000))
    entry_dir = os.path.join(PENDING_DIR, entry_id)
    os.makedirs(entry_dir, exist_ok=True)

    manifest = {
        "id": entry_id,
        "action": args.action,
        "target_skill": args.target or None,
        "scope": args.scope,
        "path": args.path if args.action == "remove_file" else None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "approved_at": None,
    }
    _save_manifest(os.path.join(entry_dir, "manifest.json"), manifest)

    print(entry_id)


def _entry_status(manifest):
    if manifest.get("rejected_at"):
        return "rejected"
    if manifest.get("approved_at"):
        return "awaiting skill-creator"
    return "awaiting approval"


def cmd_list(args):
    if not os.path.isdir(PENDING_DIR):
        return
    entries = sorted(os.listdir(PENDING_DIR))
    if not entries:
        return
    show_all = getattr(args, "all", False)
    for entry_id in entries:
        _, manifest = _load_manifest(entry_id)
        status = _entry_status(manifest)
        if status == "rejected" and not show_all:
            continue
        target = manifest["target_skill"] or "(new)"
        print(f"{entry_id}\t{manifest['action']}\t{target}\t{status}")


def cmd_show(args):
    _, manifest = _load_manifest(args.id)
    print(json.dumps(manifest, indent=2))


def _skill_mtime(base):
    """Latest mtime among all files under base, or None if base doesn't exist."""
    if not os.path.isdir(base):
        return None
    latest = None
    for root, _dirs, files in os.walk(base):
        for name in files:
            mtime = os.path.getmtime(os.path.join(root, name))
            if latest is None or mtime > latest:
                latest = mtime
    return latest


def cmd_approve(args):
    manifest_path, manifest = _load_manifest(args.id)
    if manifest.get("rejected_at"):
        print(
            f"pending.py approve: {args.id} was rejected at {manifest['rejected_at']} "
            f"— cannot approve a rejected entry. Stage a new request instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    entry_dir = os.path.dirname(manifest_path)
    action = manifest["action"]
    target = manifest["target_skill"]
    scope = manifest.get("scope")
    skills_root = _skills_root(scope)

    if action in MECHANICAL_ACTIONS:
        if action == "delete":
            target_path = os.path.join(skills_root, target)
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
        elif action == "remove_file":
            dest = os.path.join(skills_root, target, manifest["path"])
            if os.path.exists(dest):
                os.remove(dest)
        shutil.rmtree(entry_dir)
        print(f"approved {args.id}: {action} {target or '(new)'}")
        return

    if manifest.get("approved_at"):
        print(
            f"pending.py approve: {args.id} was already approved at "
            f"{manifest['approved_at']} — still waiting for skill-creator to "
            f"finish {action} on '{target}'."
        )
        return

    manifest["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_manifest(manifest_path, manifest)

    print(
        f"approved {args.id}: invoke skill-creator now for {action} '{target}' "
        f"(scope {scope or _load_config().get('scope', 'project')}) — write directly "
        f"to .claude/skills/{target}/. This entry clears itself once the change lands."
    )


def _reset_mentions(target):
    """Zero the mention counter for a domain that was rejected."""
    if not target or not os.path.exists(MENTIONS_PATH):
        return
    try:
        with open(MENTIONS_PATH) as f:
            mentions = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return
    if target in mentions:
        del mentions[target]
        with open(MENTIONS_PATH, "w") as f:
            json.dump(mentions, f, indent=2)


def cmd_reject(args):
    manifest_path, manifest = _load_manifest(args.id)
    if manifest.get("rejected_at"):
        print(f"pending.py reject: {args.id} already rejected at {manifest['rejected_at']}.")
        return
    manifest["rejected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_manifest(manifest_path, manifest)
    _reset_mentions(manifest.get("target_skill"))
    target = manifest["target_skill"] or "(new)"
    print(f"rejected {args.id}: {manifest['action']} {target} — kept for history, mention counters reset")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new")
    p_new.add_argument("--action", required=True,
                        choices=["create", "patch", "edit", "delete", "write_file", "remove_file"])
    p_new.add_argument("--target", default="")
    p_new.add_argument("--scope", choices=["project", "user"], default=None)
    p_new.add_argument("--path", default=None,
                        help="remove_file only: relative path (within the target skill) to remove")
    p_new.set_defaults(func=cmd_new)

    p_list = sub.add_parser("list")
    p_list.add_argument("--all", action="store_true", help="Include rejected entries")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("id")
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject")
    p_reject.add_argument("id")
    p_reject.set_defaults(func=cmd_reject)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
