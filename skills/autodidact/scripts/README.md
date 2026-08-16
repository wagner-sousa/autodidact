# autodidact hook wiring

Four scripts, tool-agnostic in logic:

- `detect_complexity.py` — Stop hook. Reads the hook JSON payload from stdin, needs `transcript_path` (path to the JSONL conversation transcript). Counts `tool_use` blocks in the last turn; if >= threshold, writes `.state/pending.json`. This is a cheap backstop only — the real trigger is the agent's own end-of-task judgment (see `SKILL.md`).
- `inject_reminder.sh` — UserPromptSubmit hook. If `.state/pending.json` exists, prints the skill_manage trigger text (consumed as injected context) and deletes the marker.
- `pending.py` — CLI for the async approval queue (`new`/`list`/`show`/`approve`/`reject`). Mirrors Hermes' `write_approval` staging: proposals land in `.state/pending/<id>/` and survive restarts until approved or rejected.
- `list_pending.sh` — SessionStart hook. Prints any pending proposals so they aren't forgotten between sessions.

### Trigger (multi-signal, mirrors self-improving-skills)

Two independent paths in `detect_complexity.py`'s `should_fire()`: an edit-heavy turn fires on a lower tool-call bar, a pure-readonly turn needs more evidence.

`config.json`'s `"trigger"` object (tracked in git, project-wide default):
```json
{"trigger": {"min_tool_calls": 5, "min_file_edits": 2, "readonly_threshold": 12}}
```
- `min_tool_calls` — minimum tool calls for an edit-heavy turn (`edit_count >= min_file_edits`) to fire. Override with `SKILL_MANAGE_THRESHOLD` env var (this key only, highest precedence).
- `min_file_edits` — minimum `Edit`/`Write`/`NotebookEdit` calls to count as edit-heavy.
- `readonly_threshold` — for turns with zero file edits, the (higher) tool-call bar needed to fire instead.

Precedence: `SKILL_MANAGE_THRESHOLD` env var > `config.json["trigger"]` > defaults above.

### write_approval

`config.json` `"write_approval"` (default `true`) mirrors Hermes' own flag:
- `true` — `pending.py new` only stages the proposal; nothing touches `.claude/skills/` until `approve <id>`.
- `false` — `pending.py new` applies immediately (skip the queue), same effect as Hermes running with the gate disabled. Use only in trusted/throwaway setups.

### scope

`config.json` `"scope"` (default `"project"`) picks the skill storage root:
- `"project"` — `.claude/skills/` of the current repo, versioned in git.
- `"user"` — `~/.claude/skills/`, survives `git clone`/`reset`, shared across projects.

Override per-proposal with `pending.py new --scope project|user` (does not touch `config.json`, applies to that one entry only — the scope is recorded in the manifest and reused at `approve` time).

## Claude Code

Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/detect_complexity.py" }
      ]}
    ],
    "UserPromptSubmit": [
      { "hooks": [
        { "type": "command", "command": "bash .claude/skills/autodidact/scripts/inject_reminder.sh" }
      ]}
    ],
    "SessionStart": [
      { "hooks": [
        { "type": "command", "command": "bash .claude/skills/autodidact/scripts/list_pending.sh" }
      ]}
    ]
  }
}
```

Merge these entries into existing `Stop`/`UserPromptSubmit`/`SessionStart` arrays instead of replacing them if the project already has hooks there.

## OpenCode / other agents

Same two scripts work unmodified as long as the host:
1. Exposes a Stop-equivalent event with the transcript path (JSONL, Anthropic message format) piped as JSON on stdin.
2. Exposes a prompt-submit-equivalent event whose stdout gets injected as context for the next turn.

If the host's transcript format differs, only `last_turn_tool_calls()` in `detect_complexity.py` needs adapting — the marker file contract (`.state/pending.json` with `tool_call_count` and `tools_used`) stays the same, so `inject_reminder.sh` never needs to change.

## Installing in a project

```bash
cp -r skills/autodidact <target-project>/.claude/skills/
```

Then add the hook entries above to the target project's settings.
