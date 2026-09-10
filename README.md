# autodidact

![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)
[![agentskills.io](https://img.shields.io/badge/agentskills.io-compatible-FF6B35?style=for-the-badge&logo=bookstack&logoColor=white)](https://agentskills.io)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)

> A procedural-memory self-improvement loop for any [agentskills.io](https://agentskills.io)-compatible AI coding agent, modeled on a `skill_manage`-style tool and its async approval queue.

---

## About

At the end of a task, autodidact asks: *did we just learn something worth not
re-deriving next time?* If so, it drafts a skill (new, or a patch to an existing
one), runs it past a guard step, and stages it in an async approval queue instead of
writing straight to `.claude/skills/`.

Agent conversations regularly involve reverse-engineering undocumented behavior,
working around a trap in a specific order of steps, or getting corrected by the user
on a preference the code doesn't state. That knowledge is usually gone at the end of
the session. autodidact turns the highest-signal moments of a conversation into
durable, reusable skills — without ever writing to disk without a review step.

Two triggers, mirroring that pattern:

- **The agent's own judgment (primary).** At the natural end of any task, regardless
  of whether a hook fired.
- **A Stop-hook nudge (backstop).** `detect_complexity.py` counts tool calls in the
  last turn and injects a reminder past a threshold — a cheap catch-all, not a
  substitute for judgment.

Six proposal actions, mirroring that `skill_manage` shape: `create`, `patch`, `edit`,
`delete`, `write_file`, `remove_file`.

---

## Technologies

- **[agentskills.io](https://agentskills.io) SKILL.md format** — the plugin is
  agent-agnostic by design: it targets any agent (Claude Code, OpenCode, or otherwise)
  that supports this open skill spec plus Stop/UserPromptSubmit/SessionStart-equivalent
  hooks.
- **Python 3** — all scripts and hooks (`pending.py`, `inject_reminder.py`,
  `detect_domain_recurrence.py`, `detect_complexity.py`, `detect_pending_completion.py`,
  `detect_staleness.py`, `list_pending.py`, `install_hooks.py`), stdlib only, no
  external dependencies.

---

## Prerequisites

- Any [agentskills.io](https://agentskills.io)-compatible AI coding agent with
  Stop/UserPromptSubmit/SessionStart-equivalent hooks (e.g. Claude Code, OpenCode).
- Python 3, available on `PATH` as `python3`.

- Optionally, a `skill-creator` skill installed in your project — see
  [Pairing with a skill-creator](#pairing-with-a-skill-creator) below. autodidact
  works without one; it just skips the guard step.

---

## Installation

### Clone the repository

```bash
git clone https://github.com/wagner-sousa/autodidact.git
cd autodidact
```

### Copy the plugin into your project

Paths below use Claude Code's layout as the example — swap `.claude/` for your
agent's own skills/commands directory if it differs.

```bash
cp -r skills/autodidact <your-project>/.claude/skills/
cp commands/*.md <your-project>/.claude/commands/
```

### Wire the hooks

The fastest way is the install script — it is idempotent, detects existing hooks by
script filename, and handles both relative and absolute command paths:

```bash
# Project-level (.claude/settings.json)
python3 .claude/skills/autodidact/scripts/install_hooks.py

# User-level (~/.claude/settings.json) — hooks use absolute paths so they work
# in any project
python3 .claude/skills/autodidact/scripts/install_hooks.py --user

# Dry-run: check status without writing
python3 .claude/skills/autodidact/scripts/install_hooks.py --check
```

Alternatively, `hooks/hooks.json` contains the ready-to-use
Stop/UserPromptSubmit/SessionStart block you can merge manually:

```bash
cp hooks/hooks.json <your-project>/.claude/hooks.json
# then merge the "hooks" key into .claude/settings.json
```

See `skills/autodidact/README.md` for the full explanation of each hook,
including non-Claude-Code agents.

---

## Configuration

`skills/autodidact/config.json` (tracked in git, project-wide):

```json
{
  "scope": "project",
  "auto_approve": false,
  "trigger": {
    "min_tool_calls": 5,
    "min_file_edits": 2,
    "readonly_threshold": 8
  }
}
```

| Key | Default | Effect |
| --- | --- | --- |
| `scope` | `"project"` | `"project"` = write to `.claude/skills/` (versioned, this repo only). `"user"` = write to `~/.claude/skills/` (survives clone/reset, shared across projects). |
| `auto_approve` | `false` | `true` = skip the `AskUserQuestion` prompt and approve staged requests automatically — skill-creator drafts and writes in the background with no human in the loop. |
| `trigger.min_tool_calls` | `5` | Stop-hook backstop: minimum tool calls in an edit-heavy turn to fire. |
| `trigger.min_file_edits` | `2` | Minimum `Edit`/`Write`/`NotebookEdit` calls for a turn to count as edit-heavy. |
| `trigger.readonly_threshold` | `8` | For read-only turns, the higher tool-call bar needed to fire instead. |

`SKILL_MANAGE_THRESHOLD` (env var) overrides `trigger.min_tool_calls` only, taking
precedence over `config.json`.

---

## Project Structure

```shell
autodidact/
├── skills/
│   └── autodidact/
│       ├── SKILL.md               # the loop: when it fires, how to propose/approve
│       ├── SKILL_CREATOR.md       # how to pair autodidact with a skill-creator
│       ├── config.json            # scope / trigger / domain_recurrence settings
│       └── scripts/
│           ├── detect_complexity.py         # Stop hook
│           ├── detect_pending_completion.py # Stop hook
│           ├── detect_staleness.py          # Stop hook
│           ├── inject_reminder.py           # UserPromptSubmit hook
│           ├── detect_domain_recurrence.py  # UserPromptSubmit hook
│           ├── pending.py                   # approval queue CLI
│           ├── list_pending.py              # SessionStart hook
│           ├── install_hooks.py             # hook installer
│           └── README.md                    # hook wiring instructions
├── commands/
│   ├── skill-learn.md             # /skill-learn
│   ├── skill-fork.md              # /skill-fork
│   └── skills-curator.md          # /skills-curator
├── hooks/
│   └── hooks.json                 # ready-to-merge Stop/UserPromptSubmit/SessionStart block
├── LICENSE
└── README.md
```

---

## Usage

Once installed, the loop runs on its own — no action needed for the default,
judgment-driven path. To drive it explicitly:

```bash
# Distill a skill from the current conversation, a path, a URL, or notes
/skill-learn

# Fork an external skill (Anthropic's, OpenAI's, or any repo) into your project
/skill-fork https://github.com/anthropics/skills/tree/main/skills/skill-creator

# Read-only health report on your skill library
/skills-curator
```

Manage proposals directly with the queue CLI:

```bash
python3 .claude/skills/autodidact/scripts/pending.py list
python3 .claude/skills/autodidact/scripts/pending.py show <id>
python3 .claude/skills/autodidact/scripts/pending.py approve <id>
python3 .claude/skills/autodidact/scripts/pending.py reject <id>
```

### Pairing with a skill-creator

autodidact's guard step reviews every drafted skill against a `skill-creator` skill
before staging it. It doesn't bundle one — fork an existing implementation instead of
reinventing it:

- Anthropic: https://github.com/anthropics/skills/tree/main/skills/skill-creator
- OpenAI: https://github.com/openai/skills/blob/main/skills/.system/skill-creator

See `skills/autodidact/SKILL_CREATOR.md` for the recommended fork workflow
(provenance stamping, layering your own conventions on top, re-syncing with
upstream). autodidact still works without a `skill-creator` installed — the guard
step is skipped rather than blocking the proposal.

---

## Architecture

<!-- Diagram source: https://mermaid.live -->

```mermaid
graph TB
    Task[Agent finishes a task] --> Judge{Worth capturing?}
    Hook[Stop hook: unconditional reminder + tool-count backstop] -.reminder.-> Judge
    Recur[UserPromptSubmit: same domain mentioned repeatedly] -.stages itself.-> Queue
    Stale[Stop hook: skill exists but files edited, never invoked] -.stages patch.-> Queue
    Judge -- no --> Skip[Skip silently]
    Judge -- yes --> Stage[pending.py new: request only, no content]
    Stage --> Queue[(.state/pending/id — manifest.json)]
    Queue --> Ask[AskUserQuestion at end of task]
    Ask -- decide later --> Queue
    Ask -- reject --> Rejected[rejected_at stamped, kept as history, mention counter reset]
    Ask -- approve --> Mechanical{delete / remove_file?}
    Mechanical -- yes --> Applied[Applied immediately, entry cleared]
    Mechanical -- no --> Fork[Fork subagent: skill-creator drafts, writes directly to .claude/skills/]
    Fork -.background.-> Skills[(.claude/skills/)]
    Skills --> Watch[Stop hook: detect_pending_completion.py]
    Watch -- files changed since approval --> Cleared[Entry auto-cleared]
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for
details.

---

## Contact

**Wagner Sousa**

[![GitHub](https://img.shields.io/badge/GitHub-wagner--sousa-181717?style=for-the-badge&logo=github)](https://github.com/wagner-sousa)

---
