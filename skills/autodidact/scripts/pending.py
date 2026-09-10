#!/usr/bin/env python
"""autodidact pending queue — async approval queue.

Instead of asking for a yes/no in the same turn, a proposal is staged as a
pending entry that survives restarts. The user reviews and approves/rejects
whenever they want, in a later session if needed. Every proposal is queued —
nothing is ever written to .claude/skills/ without an explicit approve.

approve re-validates the applied SKILL.md files against the same structural
checks new() runs, and rolls back to the pre-apply snapshot (or deletes a
newly-created dir) if anything comes out malformed — the entry stays queued
for a fix and re-approve instead of leaving a broken skill on disk.

Usage:
  pending.py new --action create|patch|edit|delete|write_file|remove_file \
                  --target <skill-name-or-empty> --summary "..." \
                  [--file <relative/path>=<path-to-staged-content-on-disk>]... \
                  [--scope project|user]
  pending.py list
  pending.py show <id>       # full manifest + staged file content
  pending.py diff <id>       # unified diff: current skill vs staged
  pending.py approve <id>
  pending.py reject <id>
"""
import argparse
import difflib
import json
import os
import re
import shutil
import sys
import tempfile
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


FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _validate_skill_md(rel_path, content, target):
    """Deterministic sanity checks only — no LLM judgment here. Catches the
    obvious breakage (missing/malformed frontmatter, name/dir mismatch)
    before it reaches the approval queue; anything requiring domain
    judgment is skill-creator's job, not this script's."""
    if os.path.basename(rel_path) != "SKILL.md":
        return []

    errors = []
    match = FRONTMATTER_RE.match(content)
    if not match:
        errors.append(f"{rel_path}: missing or malformed YAML frontmatter (must start with '---' block)")
        return errors

    frontmatter = match.group(1)
    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)

    if not name_match:
        errors.append(f"{rel_path}: frontmatter missing 'name' field")
    elif target and name_match.group(1).strip().strip("\"'") != target:
        errors.append(
            f"{rel_path}: frontmatter name '{name_match.group(1).strip()}' "
            f"does not match target skill '{target}'"
        )

    if not desc_match or not desc_match.group(1).strip():
        errors.append(f"{rel_path}: frontmatter missing or empty 'description' field")

    return errors


def cmd_new(args):
    errors = []
    for spec in args.file or []:
        rel_path, staged_content_path = spec.split("=", 1)
        if args.action not in ("delete", "remove_file") and os.path.basename(rel_path) == "SKILL.md":
            with open(staged_content_path) as fh:
                errors.extend(_validate_skill_md(rel_path, fh.read(), args.target))

    if errors:
        for err in errors:
            print(f"pending.py new: {err}", file=sys.stderr)
        print("pending.py new: refusing to stage, fix the errors above first", file=sys.stderr)
        sys.exit(1)

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


def cmd_diff(args):
    manifest_path, manifest = _load_manifest(args.id)
    action = manifest["action"]
    target = manifest["target_skill"]
    skills_root = _skills_root(manifest.get("scope"))
    base = os.path.join(skills_root, target) if target else skills_root
    files_dir = os.path.join(os.path.dirname(manifest_path), "files")
    any_diff = False

    for f in manifest["files"]:
        staged = os.path.join(files_dir, f["staged_name"])
        dest = os.path.join(base, f["path"])

        staged_lines = open(staged).readlines() if os.path.exists(staged) else []
        current_lines = open(dest).readlines() if os.path.exists(dest) else []

        if action == "remove_file":
            staged_lines = []

        diff = list(difflib.unified_diff(
            current_lines, staged_lines,
            fromfile=f"a/{f['path']}", tofile=f"b/{f['path']}",
        ))
        if diff:
            any_diff = True
            print("".join(diff))

    if not any_diff:
        print(f"no changes (staged matches current or files are new with identical content)")


def _snapshot(path):
    """Back up path to a tempdir before applying. Returns the tempdir, or None
    if path doesn't exist yet (nothing to restore, just delete on rollback)."""
    if not os.path.isdir(path):
        return None
    snap = tempfile.mkdtemp(prefix="autodidact-snap-")
    shutil.copytree(path, os.path.join(snap, "content"))
    return snap


def _restore(target_path, snapshot):
    """Revert target_path to snapshot's content, discarding the snapshot dir."""
    if os.path.isdir(target_path):
        shutil.rmtree(target_path)
    if snapshot:
        shutil.move(os.path.join(snapshot, "content"), target_path)
        shutil.rmtree(snapshot, ignore_errors=True)


def cmd_approve(args):
    manifest_path, manifest = _load_manifest(args.id)
    entry_dir = os.path.dirname(manifest_path)
    action = manifest["action"]
    target = manifest["target_skill"]
    scope = manifest.get("scope")
    skills_root = _skills_root(scope)
    base = os.path.join(skills_root, target) if target else skills_root

    snapshot = None
    if action in ("create", "patch", "edit", "write_file") and target:
        snapshot = _snapshot(base)

    _apply(action, target, os.path.join(entry_dir, "files"), manifest["files"], scope)

    errors = []
    if action in ("create", "patch", "edit", "write_file"):
        for f in manifest["files"]:
            if os.path.basename(f["path"]) == "SKILL.md":
                dest = os.path.join(base, f["path"])
                if os.path.exists(dest):
                    with open(dest) as fh:
                        errors.extend(_validate_skill_md(f["path"], fh.read(), target))

    if errors:
        _restore(base, snapshot)
        for err in errors:
            print(f"pending.py approve: {err}", file=sys.stderr)
        print(
            f"pending.py approve: post-apply validation failed, rolled back — "
            f"entry {args.id} stays in the queue for a fix and re-approve.",
            file=sys.stderr,
        )
        sys.exit(1)

    if snapshot:
        shutil.rmtree(snapshot, ignore_errors=True)
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

    p_diff = sub.add_parser("diff")
    p_diff.add_argument("id")
    p_diff.set_defaults(func=cmd_diff)

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
