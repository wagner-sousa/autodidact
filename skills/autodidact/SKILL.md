---
name: autodidact
description: "Procedural memory self-improvement loop (Hermes-style skill_manage). Self-evaluates at the end of any task, complex or not, whether a workflow deserves to become or update a skill; the Stop-hook tool-count nudge is only a cheap backstop. Stages proposals to an async approval queue (create/patch/edit/delete/write_file/remove_file) instead of asking yes/no inline. Triggers: pending skill review, review a skill, pending learning, you discovered something, approve skill, what's pending, pending skills."
---

# Autodidact — Procedural Memory Loop

This skill activates after complex turns to evaluate whether the work just done should be persisted as a new skill or a patch to an existing one.
It is the Claude Code equivalent of Hermes Agent's `skill_manage` tool + `write_approval` gate.

## When this skill fires

Two paths, and both are valid — this mirrors how Hermes actually works: the trigger is the agent's own judgment, not a fixed rule. `write_approval: true` gates the write, not the decision to propose.

1. **Your own judgment (primary).** At the natural end of any task, ask yourself the questions below regardless of whether a hook fired. A workflow can be worth capturing after 2 tool calls (a genuinely tricky one-liner) or not worth it after 15 (repetitive, uninteresting). Don't wait for permission to evaluate.
2. **The Stop hook nudge (backstop, cheap and dumb on purpose).** `scripts/detect_complexity.py` counts `tool_use` blocks in the transcript and injects a reminder past a threshold. It exists only to catch cases where you finished a complex turn and moved on without pausing to reflect — it is not a substitute for judgment, and a turn crossing the threshold does not mean you must propose something.

## Evaluation checklist

Before proposing anything, run through these questions mentally:

1. **Was something non-obvious discovered?** (reverse-engineered a flow, hit a dead end and pivoted, learned a hidden constraint)
2. **Would future-you need this again?** (not a one-off, not already documented in the codebase)
3. **Is it procedural?** (a workflow, sequence of commands, decision tree) — if it is just a fact, save to memory instead.
4. **Does an existing skill already own this domain?** (prefer a patch over a new skill — fewer files, less drift)

If two or more answers are "yes", propose. Otherwise, skip silently.

## Action vocabulary

Same six actions Hermes' `skill_manage` tool exposes. Pick the narrowest one that fits — `patch` is preferred over `edit` for the same reason a diff beats a rewrite: cheaper to review, less drift.

| Action | When | Claude Code equivalent |
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

## Skill guard

Before staging any `create`, `patch`, or `edit` proposal, run the drafted `SKILL.md` content past a `skill-creator` skill for a structural review — this is our stand-in for Hermes' guard, which snapshots and reverts malformed skills. See [SKILL_CREATOR.md](SKILL_CREATOR.md) for how to get a `skill-creator` skill (fork Anthropic's or OpenAI's implementation) into your project. Because `skill-creator` is typically an interactive draft→test→review flow, not a headless validator, invoke it through a subagent instead of inline:

1. Write the drafted `SKILL.md` (and any reference files) to a temp path — same content you're about to stage.
2. Launch a subagent (`Agent` tool, fresh general-purpose agent) with a self-contained prompt: review the temp files against your `skill-creator`'s conventions (language, frontmatter shape, description quality/triggers, no orphaned references, scope/size sanity). Ask it to report pass/fail plus concrete fixes, not to rewrite the skill itself.
3. If the guard reports problems, fix the temp files before staging. If it passes (or the subagent errors out — don't block on infra flakiness), proceed to staging below.

Skip the guard only for `delete`/`remove_file` (nothing to validate) and for trivial `write_file` additions (e.g. a reference doc, not `SKILL.md` itself). If your project has no `skill-creator` skill installed, skip the guard entirely rather than blocking the proposal.

## Proposal format

Stage a pending entry instead of writing directly and instead of blocking the turn on a yes/no — this is the async approval queue Hermes uses (`write_approval`), not a synchronous prompt. Write the proposed content to a temp file, then stage it:

```bash
python3 .claude/skills/autodidact/scripts/pending.py new \
  --action patch --target <skill-name> \
  --summary "one line: what and why" \
  --file "references/new-doc.md=/tmp/staged-content.md"
```

`pending.py new` behaves according to `config.json`'s `write_approval`:
- `true` (queue, default) — prints the entry id. Tell the user, in one line, that a proposal was staged and how to act on it — don't wait for a reply before moving on:
  ```
  autodidact: staged <action> for <skill-name> (id <id>) — "python3 .claude/skills/autodidact/scripts/pending.py show <id>" to review, "approve <id>" / "reject <id>" to decide, whenever convenient.
  ```
- `false` (auto-apply) — the write already happened. Always tell the user in one line what changed, right after the call:
  ```
  autodidact: <action> applied to <skill-name> — <one-line summary>.
  ```
  Never apply silently, even though no approval step blocks it.

For `create`, `edit`, and `write_file`, `--file` can be repeated for multiple files. For `delete`/`remove_file`, omit `--file` content (staging still records which paths/target will be removed).

## Approval

Never write to `.claude/skills/` outside this queue. The pending queue survives restarts (`.state/pending/`, gitignored) and is surfaced automatically at `SessionStart` (`scripts/list_pending.sh`) so nothing gets lost between sessions.

- **Approve**: `python3 .claude/skills/autodidact/scripts/pending.py approve <id>` — applies the staged files/removal to `.claude/skills/`.
- **Reject**: `python3 .claude/skills/autodidact/scripts/pending.py reject <id>` — discards, no trace left.
- If the user asks to see or decide on a proposal in conversation ("approve skill X", "what's pending"), run `pending.py list`/`show`/`approve`/`reject` on their behalf rather than making them type the command.
- After an approval that touches tracked files, follow the project's commit convention if the user wants it committed — don't commit unprompted.

## Portability

This skill and its scripts form a self-contained plugin: `detect_complexity.py` (Stop backstop), `inject_reminder.sh` (UserPromptSubmit nudge), `pending.py` (async approval queue), `list_pending.sh` (SessionStart visibility).
To install in a project (Claude Code, OpenCode, or any agent that supports agentskills.io + shell hooks):
1. Copy this directory to `.claude/skills/autodidact/` (or equivalent skills path).
2. Add the three hook entries from `scripts/README.md` to the project's hook config.

## Configuration

`config.json` (tracked in git, project-wide):

| Key | Default | Effect |
|---|---|---|
| `write_approval` | `true` | `true` = stage proposals in the async queue (Hermes default). `false` = apply immediately, no queue. |
| `scope` | `"project"` | Where skills are written: `"project"` = `.claude/skills/` (versioned, this repo only). `"user"` = `~/.claude/skills/` (survives git clone/reset, shared across projects). Override per-proposal with `pending.py new --scope project\|user`. |
| `trigger.min_tool_calls` | `5` | Stop-hook backstop: minimum tool calls in an edit-heavy turn (see `trigger.min_file_edits`) to fire. Override with `SKILL_MANAGE_THRESHOLD` env var (overrides this key only). |
| `trigger.min_file_edits` | `2` | Minimum `Edit`/`Write`/`NotebookEdit` calls for a turn to count as edit-heavy and use the lower `min_tool_calls` bar. |
| `trigger.readonly_threshold` | `12` | For turns with zero file edits (pure investigation), the higher tool-call bar needed to fire instead — more evidence required before proposing on a read-only turn. |

## Reference files

- `SKILL_CREATOR.md` — how to fork or build a `skill-creator` skill to pair with this plugin's guard step.
- `scripts/README.md` — hook wiring instructions (Claude Code, OpenCode, other adapters).
