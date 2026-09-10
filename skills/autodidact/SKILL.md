---
name: autodidact
description: "Procedural memory self-improvement loop (skill_manage-style). Self-evaluates at the end of any task, complex or not, whether a workflow deserves to become or update a skill; the Stop-hook tool-count nudge is only a cheap backstop. Stages requests (create/patch/edit/delete/write_file/remove_file) to an async approval queue; approve triggers skill-creator to draft/write directly, a Stop hook auto-clears the request once done. Triggers: pending skill review, review a skill, pending learning, you discovered something, approve skill, what's pending, pending skills."
---

# Autodidact — Procedural Memory Loop

This skill activates after complex turns to evaluate whether the work just done should be persisted as a new skill or a patch to an existing one.
It is an async approval-queue pattern (`skill_manage`-style) — agent-agnostic by design, tested primarily on Claude Code but portable to any agent that supports the SKILL.md spec plus equivalent hooks.

## When this skill fires

Three paths, and all are valid — this mirrors that pattern: the trigger is the agent's own judgment, not a fixed rule. Every proposal lands in the pending queue — nothing is ever written to `.claude/skills/` without an explicit approve.

1. **Your own judgment (primary).** At the natural end of any task, ask yourself the questions below regardless of whether a hook fired. A workflow can be worth capturing after 2 tool calls (a genuinely tricky one-liner) or not worth it after 15 (repetitive, uninteresting). Don't wait for permission to evaluate.
2. **The Stop hook nudge (backstop, cheap and dumb on purpose).** `scripts/detect_complexity.py` runs on every turn. It unconditionally prints a reminder covering four capture-worthy criteria: (a) 5+ tool calls that succeeded, (b) an error or dead end you worked around, (c) the user correcting your approach, or (d) a non-obvious flow you discovered. (b)-(d) can happen in one or two tool calls — no tool-count threshold would ever catch them, so the reminder fires every turn regardless of volume. Separately, it also counts `tool_use` blocks and, past the configured threshold, writes a marker so `inject_reminder.py` injects a richer count-based nudge at the start of the next turn. Neither path is a substitute for judgment — crossing a threshold, or a turn ending at all, does not mean you must propose something.
3. **The domain-recurrence nudge (detection-only).** `scripts/detect_domain_recurrence.py` watches for the same uncovered domain coming up repeatedly across separate prompts — a pattern `detect_complexity.py` misses because no single turn crosses its tool-call bar. It never generates skill content and never stages a request itself — a deterministic script has no domain knowledge beyond a name match. Once it fires, it reminds the agent to stage a request (`pending.py new --action create --target <domain>`). It fires on every subsequent mention (not just the first) until the skill directory exists.

## Evaluation checklist

Before proposing anything, run through these questions mentally:

1. **Was something non-obvious discovered?** (reverse-engineered a flow, hit a dead end and pivoted, learned a hidden constraint)
2. **Would future-you need this again?** (not a one-off, not already documented in the codebase)
3. **Is it procedural?** (a workflow, sequence of commands, decision tree) — if it is just a fact, save to memory instead.
4. **Does an existing skill already own this domain?** (prefer a patch over a new skill — fewer files, less drift)

If two or more answers are "yes", propose. Otherwise, skip silently.

## Action vocabulary

Same six actions a `skill_manage`-style tool exposes. Pick the narrowest one that fits — `patch` is preferred over `edit` for the same reason a diff beats a rewrite: cheaper to review, less drift.

| Action | When | Filesystem equivalent |
|---|---|---|
| `create` | No existing skill owns the topic and it is broad enough to recur | new `<name>/SKILL.md` |
| `patch` | An existing skill owns the topic; adding a section/reference file is enough | `Edit`/`Write` inside that skill's dir |
| `edit` | An existing skill is structurally wrong or outdated, not just missing a piece | full rewrite of `SKILL.md` |
| `delete` | A skill is superseded or was created in error | remove the skill's directory |
| `write_file` | Add a supporting file (reference/script/asset) without touching `SKILL.md` | `Write` under `references/`, `scripts/`, etc. |
| `remove_file` | Remove a stale supporting file | delete the file |

## Decision: new skill vs patch vs edit

```
Does any existing skill own this topic?
  No  → create (only if the topic is broad enough to recur)
  Yes → is the existing skill just missing a piece, or structurally wrong?
          missing a piece      → patch
          structurally wrong   → edit
```

Read the current skill index before deciding: list `.claude/skills/` and skim the descriptions.

## Proposal format — request only, no content

`pending.py new` records that a create/patch/edit/delete/write_file/remove_file is wanted — it never carries the skill's content. No drafting happens at this point, so no fork is needed just to stage:

```bash
python3 .claude/skills/autodidact/scripts/pending.py new --action patch --target <skill-name>
```

For `remove_file`, add `--path <relative-path>` (the only case that needs a path — nothing to draft, just a removal target). `pending.py new` always queues and prints the entry id.

After staging, read `config.json` and branch on `auto_approve`:

**`auto_approve: true`** — approve immediately without asking:
```bash
python3 .claude/skills/autodidact/scripts/pending.py approve <id>
```
Then proceed directly into the drafting flow below. Tell the user in one line:
```
autodidact: auto-approved <action> for <skill-name> (id <id>) — generating in background.
```

**`auto_approve: false` (default)** — don't just print a notice and move on; plain text is easy to skim past. Use `AskUserQuestion` right after staging:
```
question: "Stage <action> for skill '<skill-name>' (id <id>)?"
options: ["Approve now (Recommended)", "Reject", "Decide later"]
```
- **Approve now** → run `pending.py approve <id>` immediately and continue into the drafting flow below.
- **Reject** → run `pending.py reject <id>`.
- **Decide later** → leave the entry queued; it survives restarts and resurfaces at the next `SessionStart` via `list_pending.py`.

Only fall back to a one-line text notice when the harness has no `AskUserQuestion` tool:
```
autodidact: staged <action> for <skill-name> (id <id>) — "approve <id>" / "reject <id>" whenever convenient.
```

## Approval and drafting (background fork)

Never write to `.claude/skills/` outside this flow. The pending queue survives restarts (`.state/pending/`, gitignored) and is surfaced automatically at `SessionStart` (`list_pending.py`) so nothing gets lost between sessions.

- **Approve**: `python3 .claude/skills/autodidact/scripts/pending.py approve <id>`.
  - For `delete`/`remove_file`: applies immediately (nothing to draft) and clears the entry itself.
  - For `create`/`patch`/`edit`/`write_file`: stamps the entry "approved" and prints an instruction to invoke `skill-creator` now for that target — **this is your cue to draft**. The entry is NOT removed yet; it stays queued until the skill actually lands on disk.
- **Reject**: `python3 .claude/skills/autodidact/scripts/pending.py reject <id>` — discards, no trace left.
- If the user asks to see or decide on a proposal in conversation ("approve skill X", "what's pending"), run `pending.py list`/`show`/`approve`/`reject` on their behalf rather than making them type the command.

Once approved, drafting is noisy (exploration, iteration) and doesn't belong in the main conversation. Use a **fork** (Claude Code's `Agent` tool with `subagent_type: "fork"`, or your agent's equivalent background-with-shared-context mechanism): it inherits full context, runs in the background, and keeps its tool output out of the main session.

See [SKILL_CREATOR.md](SKILL_CREATOR.md) for how to get a `skill-creator` skill (fork Anthropic's or OpenAI's implementation) into your project.

1. Launch a fork with a directive like:
   ```
   An autodidact request for <action> on '<target>' was just approved (id <id>).
   1. Invoke skill-creator to draft SKILL.md for this domain (or patch/edit/extend
      the existing one) — write directly to .claude/skills/<target>/, no staging step.
   2. SendMessage("main", "autodidact: <target> is ready — skill-creator finished (id <id>).")
   3. If you can't produce something you're confident in, SendMessage("main",
      "autodidact: couldn't draft <target> (id <id>) — <why>. Needs manual attention.")
      and leave the entry approved-but-pending rather than writing something bad.
   ```
2. Don't wait for the fork — continue your own turn. The `detect_pending_completion.py` Stop hook watches `.claude/skills/<target>/` and clears the pending entry automatically once it sees the files change after the approval timestamp — no manual cleanup needed.
3. When the fork's message arrives, relay it to the user in one line if you're still in the same session.

Skip the fork only for trivial hand-edits you're already confident about. If your project has no `skill-creator` skill installed, draft the `SKILL.md` yourself instead of blocking the request — same completion detection applies either way.

## Portability

This skill and its scripts form a self-contained plugin: `detect_complexity.py` (Stop backstop), `inject_reminder.py` (UserPromptSubmit nudge), `detect_domain_recurrence.py` (UserPromptSubmit domain-recurrence backstop), `pending.py` (request/approval queue), `detect_pending_completion.py` (Stop hook, auto-clears approved entries once skill-creator finishes), `list_pending.py` (SessionStart visibility), `install_hooks.py` (hook installer).
To install in a project (Claude Code, OpenCode, or any agent that supports agentskills.io + equivalent hooks):
1. Copy this directory to `.claude/skills/autodidact/` (or equivalent skills path — see `scope` in Configuration below for `.claude/skills/` vs `~/.claude/skills/`).
2. Run `python3 .claude/skills/autodidact/scripts/install_hooks.py` (add `--user` to wire `~/.claude/settings.json` instead of the project's) — it is idempotent, safe to re-run, and validates existing hooks before writing. Use `--check` to only report status. On agents other than Claude Code, add the hook entries from [README.md](README.md) to the project's hook config manually instead.

## Configuration

`config.json` (tracked in git, project-wide):

| Key | Default | Effect |
|---|---|---|
| `scope` | `"project"` | Where skills are written: `"project"` = `.claude/skills/` (versioned, this repo only). `"user"` = `~/.claude/skills/` (survives git clone/reset, shared across projects). Override per-proposal with `pending.py new --scope project\|user`. |
| `auto_approve` | `false` | `true` = skip `AskUserQuestion` and approve automatically right after staging; skill-creator runs immediately in background. `false` = ask via `AskUserQuestion` before approving. |
| `trigger.min_tool_calls` | `5` | Stop-hook backstop: minimum tool calls in an edit-heavy turn (see `trigger.min_file_edits`) to fire. Override with `SKILL_MANAGE_THRESHOLD` env var (overrides this key only). |
| `trigger.min_file_edits` | `2` | Minimum `Edit`/`Write`/`NotebookEdit` calls for a turn to count as edit-heavy and use the lower `min_tool_calls` bar. |
| `trigger.readonly_threshold` | `8` | For turns with zero file edits (pure investigation), the higher tool-call bar needed to fire instead — more evidence required before proposing on a read-only turn. |

## Reference files

- `SKILL_CREATOR.md` — how to fork or build a `skill-creator` skill to pair with this plugin's guard step.
- `README.md` — hook wiring instructions (Claude Code, OpenCode, other adapters).
