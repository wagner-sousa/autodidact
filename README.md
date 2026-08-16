# autodidact

A procedural-memory self-improvement loop for Claude Code, modeled on Hermes Agent's
`skill_manage` tool and its `write_approval` gate.

At the end of a task, autodidact asks: *did we just learn something worth not
re-deriving next time?* If so, it drafts a skill (new, or a patch to an existing one),
runs it past a guard step, and stages it in an async approval queue instead of writing
straight to `.claude/skills/`.

## Why

Agent conversations regularly involve reverse-engineering undocumented behavior,
working around a trap in a specific order of steps, or getting corrected by the user
on a preference the code doesn't state. That knowledge is usually gone at the end of
the session. autodidact turns the highest-signal moments of a conversation into
durable, reusable skills — without ever writing to disk without a review step.

## What's in this repo

```
skills/autodidact/          the plugin itself
  SKILL.md                  the loop: when it fires, what becomes a skill, how to
                             propose, how to approve
  SKILL_CREATOR.md           how to pair autodidact with a skill-creator (fork or build one)
  config.json                write_approval / scope / trigger thresholds
  scripts/
    detect_complexity.py     Stop hook — cheap tool-count backstop
    inject_reminder.sh       UserPromptSubmit hook — surfaces the backstop's reminder
    pending.py                CLI for the async approval queue (new/list/show/approve/reject)
    list_pending.sh           SessionStart hook — resurfaces anything still pending
    README.md                 hook wiring instructions

commands/                    optional slash commands that drive the loop explicitly
  skill-learn.md              /skill-learn — distill a skill from the current conversation, a path, a URL, or notes
  skill-fork.md                /skill-fork — fork an external skill (Anthropic's, OpenAI's, or any repo) into your project
  skills-curator.md            /skills-curator — read-only health report on your skill library
```

## Install

1. Copy `skills/autodidact/` into your project's `.claude/skills/`.
2. Copy `commands/*.md` into your project's `.claude/commands/` (optional, but
   recommended — they let you drive the loop explicitly instead of relying only on
   the Stop-hook backstop).
3. Wire the three hooks into `.claude/settings.json` — see
   `skills/autodidact/scripts/README.md` for the exact JSON to merge in.
4. Review `skills/autodidact/config.json` and adjust `write_approval`, `scope`, and
   the trigger thresholds for your project (defaults: queue everything, write to
   `.claude/skills/`, use the same thresholds Hermes-style self-improving-skills use).

## How it works

- **Judgment first, hook second.** The real trigger is the agent's own end-of-task
  evaluation (see `SKILL.md` → "When this skill fires"). The Stop hook
  (`detect_complexity.py`) is only a cheap backstop that counts tool calls in the
  last turn and injects a reminder — it never forces a proposal.
- **Six actions**, mirroring Hermes' `skill_manage`: `create`, `patch`, `edit`,
  `delete`, `write_file`, `remove_file`. `patch` is preferred over `edit` wherever it
  fits — cheaper to review, less drift.
- **Async approval queue.** Proposals are staged under `.state/pending/<id>/` and
  survive restarts. Nothing touches `.claude/skills/` until `pending.py approve <id>`
  runs (unless `write_approval` is set to `false`, which applies immediately — use
  only in trusted, single-user setups).
- **Guard step.** Before staging a `create`/`patch`/`edit`, the drafted `SKILL.md` is
  reviewed against your project's `skill-creator` conventions via a subagent. See
  `skills/autodidact/SKILL_CREATOR.md` for how to get a `skill-creator` skill into
  your project — fork Anthropic's, OpenAI's, or write your own.

## Pairing with a skill-creator

autodidact's guard step needs a `skill-creator` skill to review drafts against. It
doesn't bundle one — fork an existing implementation instead of reinventing it:

- Anthropic: https://github.com/anthropics/skills/tree/main/skills/skill-creator
- OpenAI: https://github.com/openai/skills/blob/main/skills/.system/skill-creator

See `skills/autodidact/SKILL_CREATOR.md` for the recommended fork workflow
(provenance stamping, layering your own conventions on top, re-syncing with
upstream). autodidact still works without a `skill-creator` installed — the guard
step is skipped rather than blocking the proposal.

## Portability

Nothing here is Claude-Code-specific beyond the hook JSON shapes documented in
`skills/autodidact/scripts/README.md`. Any agent that supports the agentskills.io
`SKILL.md` format plus Stop/UserPromptSubmit/SessionStart-equivalent hooks can run
this plugin unmodified.

## License

MIT.
