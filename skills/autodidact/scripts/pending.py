#!/usr/bin/env python
"""autodidact pending queue — async approval queue.

Instead of asking for a yes/no in the same turn, a proposal is staged as a
pending entry that survives restarts. The user reviews and approves/rejects
whenever they want, in a later session if needed.

Controlled by config.json's "auto_stage" (root):
  true  (default) — proposals are queued in .state/pending/ until approved.
  false           — proposals are applied immediately, skipping the queue.

Usage:
  pending.py new --action create|patch|edit|delete|write_file|remove_file \
                  --target <skill-name-or-empty> --summary "..." \
                  [--file <relative/path>=<path-to-staged-content-on-disk>]... \
                  [--scope project|user]
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
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _auto_stage_enabled():
    return _load_config().get("auto_stage", True)


def _skills_root(scope_override=None):
    """'project' (default) -> .claude/skills/ of this repo, versioned.
    'user' -> ~/.claude/skills/, survives git clone/reset, shared across projects."""
    scope = scope_override or _load_config().get("scope", "project")
    return USER_SKILLS_ROOT if scope == "user" else PROJECT_SKILLS_ROOT


def _apply(action, target, files_dir, files, scope=None):
    skills_root = _skills_root(scope)
    if action in ("create", "patch", "edit", "write_file"):
        base = os.path.join(skills_root, target) if target else skills_root
        for f in files:
            staged = os.path.join(files_dir, f["staged_name"])
            dest = os.path.join(base, f["path"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(staged, dest)
    elif action == "delete":
        target_path = os.path.join(skills_root, target)
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
    elif action == "remove_file":
        base = os.path.join(skills_root, target) if target else skills_root
        for f in files:
            dest = os.path.join(base, f["path"])
            if os.path.exists(dest):
                os.remove(dest)


def _load_manifest(entry_id):
    manifest_path = os.path.join(PENDING_DIR, entry_id, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"no pending entry: {entry_id}", file=sys.stderr)
        sys.exit(1)
    with open(manifest_path) as f:
        return manifest_path, json.load(f)


def cmd_new(args):
    os.makedirs(PENDING_DIR, exist_ok=True)
    entry_id = str(int(time.time() * 1000))
    entry_dir = os.path.join(PENDING_DIR, entry_id)
    os.makedirs(os.path.join(entry_dir, "files"), exist_ok=True)

    files = []
    for spec in args.file or []:
        rel_path, staged_content_path = spec.split("=", 1)
        staged_name = rel_path.replace("/", "__")
        dest = os.path.join(entry_dir, "files", staged_name)
        if args.action not in ("delete", "remove_file"):
            shutil.copyfile(staged_content_path, dest)
        files.append({"path": rel_path, "staged_name": staged_name})

    if not _auto_stage_enabled():
        _apply(args.action, args.target or None, os.path.join(entry_dir, "files"), files, args.scope)
        shutil.rmtree(entry_dir)
        print(f"applied (auto_stage=false, scope={args.scope or _load_config().get('scope', 'project')}): {args.action} {args.target or '(new)'}")
        return

    manifest = {
        "id": entry_id,
        "action": args.action,
        "target_skill": args.target or None,
        "scope": args.scope,
        "summary": args.summary,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": files,
    }
    with open(os.path.join(entry_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(entry_id)


def cmd_list(_args):
    if not os.path.isdir(PENDING_DIR):
        return
    entries = sorted(os.listdir(PENDING_DIR))
    if not entries:
        return
    for entry_id in entries:
        _, manifest = _load_manifest(entry_id)
        target = manifest["target_skill"] or "(new)"
        print(f"{entry_id}\t{manifest['action']}\t{target}\t{manifest['summary']}")


def cmd_show(args):
    _, manifest = _load_manifest(args.id)
    print(json.dumps(manifest, indent=2))
    entry_dir = os.path.join(PENDING_DIR, args.id, "files")
    for f in manifest["files"]:
        staged = os.path.join(entry_dir, f["staged_name"])
        if os.path.exists(staged):
            print(f"\n--- {f['path']} ---")
            with open(staged) as fh:
                print(fh.read())


def cmd_approve(args):
    manifest_path, manifest = _load_manifest(args.id)
    entry_dir = os.path.dirname(manifest_path)
    action = manifest["action"]
    target = manifest["target_skill"]

    _apply(action, target, os.path.join(entry_dir, "files"), manifest["files"], manifest.get("scope"))
    shutil.rmtree(entry_dir)
    print(f"approved {args.id}: {action} {target or '(new)'}")


def cmd_reject(args):
    _, manifest = _load_manifest(args.id)
    shutil.rmtree(os.path.join(PENDING_DIR, args.id))
    print(f"rejected {args.id}: {manifest['summary']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new")
    p_new.add_argument("--action", required=True,
                        choices=["create", "patch", "edit", "delete", "write_file", "remove_file"])
    p_new.add_argument("--target", default="")
    p_new.add_argument("--summary", required=True)
    p_new.add_argument("--file", action="append")
    p_new.add_argument("--scope", choices=["project", "user"], default=None,
                        help="Overrides config.json's scope for this proposal only.")
    p_new.set_defaults(func=cmd_new)

    sub.add_parser("list").set_defaults(func=cmd_list)

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
