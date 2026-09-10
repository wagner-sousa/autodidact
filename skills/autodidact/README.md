# autodidact hook wiring

These scripts implement autodidact's side of the loop: any [agentskills.io](https://agentskills.io)-compatible agent that exposes Stop/UserPromptSubmit/SessionStart-equivalent hooks can drive them. Five scripts, tool-agnostic in logic:

- `detect_complexity.py` — Stop hook. Reads the hook JSON payload from stdin, needs `transcript_path` (path to the JSONL conversation transcript). Counts `tool_use` blocks in the last turn; if >= threshold, writes `.state/pending.json`. This is a cheap backstop only — the real trigger is the agent's own end-of-task judgment (see `SKILL.md`).
- `inject_reminder.py` — UserPromptSubmit hook. If `.state/pending.json` exists, prints the skill_manage trigger text (consumed as injected context) and deletes the marker.
- `detect_domain_recurrence.py` — UserPromptSubmit hook. Reads the hook JSON payload from stdin, needs `prompt` (the user's message text). Catches the case `detect_complexity.py` can't: several small, individually-cheap turns asking about the same uncovered domain in a row, none of which alone crosses the tool-call threshold. Matches known domain terms against the prompt text and tracks per-domain mention counts in `.state/domain_mentions.json`; once a domain hits `min_mentions` without a `.claude/skills/<name>/` directory, self-stages a skeleton `create` proposal via `pending.py` (deduplicated per domain) and fires a reminder pointing at it on every further mention, resetting the counter once that skill exists. See "Domain recurrence" below.
- `pending.py` — CLI for the async approval queue (`new`/`list`/`show`/`approve`/`reject`). Every `new` proposal lands in `.state/pending/<id>/` and survives restarts until approved or rejected — nothing is ever applied without an explicit approve.
- `list_pending.py` — SessionStart hook. Prints any pending proposals so they aren't forgotten between sessions. Flags entries whose staged content still contains the auto-generated skeleton `TODO` marker (`[SKELETON]`), with an insistent reminder to fill in real content — fires every session start regardless of whether the domain is mentioned again.

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

### scope

`config.json` `"scope"` (default `"project"`) picks the skill storage root:
- `"project"` — `.claude/skills/` of the current repo, versioned in git.
- `"user"` — `~/.claude/skills/`, survives `git clone`/`reset`, shared across projects.

Override per-proposal with `pending.py new --scope project|user` (does not touch `config.json`, applies to that one entry only — the scope is recorded in the manifest and reused at `approve` time).

### Domain recurrence

`config.json`'s `"domain_recurrence"` object (tracked in git, project-wide default):
```json
{"domain_recurrence": {"min_mentions": 3, "known_domains": []}}
```
- `min_mentions` — how many times a domain can be mentioned (without an owning skill) before it fires. From that point on it fires on every subsequent mention until the skill directory exists (insistent by design).
- `known_domains` — extra terms to watch beyond what's auto-discovered. Accepts plain strings (`"mercadopago"`) or `{term: skill_dir_name}` maps when the spoken term differs from the skill's directory name (`{"nota fiscal": "fiscal"}`).

Once fired, the hook always self-stages: it calls `pending.py new --action create` itself and writes a skeleton `SKILL.md` (frontmatter + `TODO` placeholders) for the domain, so a queue entry exists without depending on the agent noticing the reminder. Deduplicated — an existing pending entry for that `target_skill` is reused instead of restaging on every mention; each print points at that entry's id. The proposal always queues (`pending.py` never applies without an explicit approve), so someone — the agent, ideally, before the user approves — has to replace the placeholder with real content. `list_pending.py` flags any entry still holding the `TODO` skeleton marker as `[SKELETON]` at every `SessionStart`, so this doesn't get forgotten if the domain isn't mentioned again.

Auto-discovery: `detect_domain_recurrence.py` looks for `src/Uoou/Component/Integration/` relative to the project root (Sylius/Symfony layout) and treats each subdirectory as a domain, stripping a trailing version suffix (`BlingV3` -> `bling`). Projects without that layout should rely on `known_domains` instead — the auto-discovery step is a no-op if the directory isn't found.

State lives in `.state/domain_mentions.json`, one counter per domain; it resets automatically once `.claude/skills/<domain>/` exists.

## Claude Code (reference implementation)

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
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/inject_reminder.py" },
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/detect_domain_recurrence.py" }
      ]}
    ],
    "SessionStart": [
      { "hooks": [
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/list_pending.py" }
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

If the host's transcript format differs, only `last_turn_tool_calls()` in `detect_complexity.py` needs adapting — the marker file contract (`.state/pending.json` with `tool_call_count` and `tools_used`) stays the same, so `inject_reminder.py` never needs to change.

## Installing in a project

```bash
cp -r skills/autodidact <target-project>/.claude/skills/
```

Then wire the hooks automatically with the install script (idempotent — safe to re-run):

```bash
# Install into project-level settings (.claude/settings.json)
python3 .claude/skills/autodidact/scripts/install_hooks.py

# Or install into user-level settings (~/.claude/settings.json)
python3 .claude/skills/autodidact/scripts/install_hooks.py --user

# Check status without writing
python3 .claude/skills/autodidact/scripts/install_hooks.py --check
```

The script detects existing hooks by script filename (basename match), so it handles
both relative and absolute command paths without duplicating entries.

The path `.claude/skills/` above is Claude Code's layout. For other agents, copy to wherever their skills directory lives and adjust the hook command paths accordingly.
