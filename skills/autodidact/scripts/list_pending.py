#!/usr/bin/env python3
"""SessionStart hook: surface any autodidact proposals still waiting for
approval, since they survive restarts (pending queue).

Reads the JSON payload from stdin (Claude Code standard), ignores it — no
payload information is needed; the queue speaks for itself.
"""
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PENDING_PY = os.path.join(SCRIPT_DIR, "pending.py")


def main():
    result = subprocess.run(
        ["python3", PENDING_PY, "list"],
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    if not output:
        return

    print("autodidact: pending proposals awaiting approval (id / action / target / summary, [SKELETON] flags entries needing real content):")
    print(output)
    print("Approve with: python3 .claude/skills/autodidact/scripts/pending.py approve <id>")
    print("Reject with:  python3 .claude/skills/autodidact/scripts/pending.py reject <id>")

    skeleton_ids = [line.split("\t", 1)[0] for line in output.splitlines() if line.endswith("[SKELETON]")]
    if skeleton_ids:
        print(
            "autodidact: the entries above marked [SKELETON] still hold TODO "
            "placeholder content (auto-staged by domain recurrence, not "
            "written by the agent). Before ending this session, replace their "
            "content with the real workflow/knowledge — "
            "'python3 .claude/skills/autodidact/scripts/pending.py show <id>' "
            "to see the placeholder, then overwrite the staged file under "
            "'.state/pending/<id>/files/' before approving. This reminder "
            "repeats every session start until the placeholder is replaced, "
            "independent of the domain being mentioned again."
        )


if __name__ == "__main__":
    main()
