# autodidact hook wiring

These scripts implement autodidact's side of the loop: any [agentskills.io](https://agentskills.io)-compatible agent that exposes Stop/UserPromptSubmit/SessionStart-equivalent hooks can drive them. Seven scripts, tool-agnostic in logic:

- `detect_complexity.py` — Stop hook. Reads the hook JSON payload from stdin, needs `transcript_path` (path to the JSONL conversation transcript). Always prints an unconditional reminder covering the four capture-worthy criteria (5+ tool calls succeeded, an error/dead-end worked around, a user correction, a non-obvious discovery) — the last three aren't detectable by counting tool calls, so this is the only reliable trigger for them. Also counts `tool_use` blocks in the last turn; if >= threshold, additionally writes `.state/pending.json` for a richer count-based nudge on the next turn. The real trigger, either way, is the agent's own end-of-task judgment (see `SKILL.md`).
- `inject_reminder.py` — UserPromptSubmit hook. If `.state/pending.json` exists, prints the skill_manage trigger text (consumed as injected context) and deletes the marker.
- `detect_domain_recurrence.py` — UserPromptSubmit hook. Reads the hook JSON payload from stdin, needs `prompt` (the user's message text). Catches the case `detect_complexity.py` can't: several small, individually-cheap turns asking about the same uncovered domain in a row, none of which alone crosses the tool-call threshold. Matches known domain terms against the prompt text and tracks per-domain mention counts in `.state/domain_mentions.json`; once a domain hits `min_mentions` without a `.claude/skills/<name>/` directory, fires a reminder on every further mention instructing the agent to stage a request via `pending.py new`. Never generates content or stages proposals itself. Resets the counter once the skill directory exists. See "Domain recurrence" below.
- `pending.py` — CLI for the async request/approval queue (`new`/`list`/`show`/`approve`/`reject`). A `new` entry only records that a create/patch/edit/delete/write_file/remove_file is wanted — it never carries the skill's content, so nothing is validated or staged at this point. `approve` on `delete`/`remove_file` applies immediately and clears the entry. `approve` on `create`/`patch`/`edit`/`write_file` just stamps `approved_at` and tells the agent to invoke `skill-creator` now, writing directly to `.claude/skills/<target>/` — the entry stays queued until that lands on disk. `reject` never deletes the entry: it stamps `rejected_at` (kept for history, hidden from plain `list`, visible with `list --all`) and zeros that domain's mention counter in `domain_mentions.json` so the same domain has to re-accumulate `min_mentions` before it can auto-stage again — this stops a rejected domain from immediately re-triggering on the next mention.
- `detect_pending_completion.py` — Stop hook. For every approved `create`/`patch`/`edit`/`write_file` entry still queued, checks whether the target skill's files changed on disk since `approved_at`; if so, skill-creator's work is done and the entry is deleted automatically. No content validation happens here — that's skill-creator's and the agent's responsibility.
- `detect_staleness.py` — Stop hook. Reads the whole session transcript (not just the last turn) for `Skill` tool invocations and `Edit`/`Write`/`NotebookEdit` file paths. Maps edited paths to known domains (same auto-discovery as `detect_domain_recurrence.py`); if a domain's files were touched, its skill directory exists, but that skill was never invoked via the `Skill` tool this session, stages a `patch` request and instructs the agent to ask via `AskUserQuestion` at the end of the task — a signal the skill may be missing something, not a signal to create a new one.
- `list_pending.py` — SessionStart hook. Prints any pending proposals so they aren't forgotten between sessions.

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

Once fired, the hook calls `pending.py new --action create --target <domain>` itself — staging a manifest is content-free and safe to do without user confirmation — then prints an instruction telling the agent to use `AskUserQuestion` on the staged id so the user decides to approve, reject, or defer. If a non-rejected entry for the target already exists, the hook reuses it rather than staging a duplicate. Generating actual `SKILL.md` content still requires domain knowledge only skill-creator has and happens only after approval. The full flow: hook stages request + tells agent to ask -> user approves -> agent invokes `skill-creator`, which drafts the real `SKILL.md` directly under `.claude/skills/<domain>/` -> `detect_pending_completion.py` clears the entry once it lands.

Auto-discovery: `detect_domain_recurrence.py` looks for `src/Uoou/Component/Integration/` relative to the project root (Sylius/Symfony layout) and treats each subdirectory as a domain, stripping a trailing version suffix (`BlingV3` -> `bling`). Projects without that layout should rely on `known_domains` instead — the auto-discovery step is a no-op if the directory isn't found.

State lives in `.state/domain_mentions.json`, one counter per domain; it resets automatically once `.claude/skills/<domain>/` exists, and also when the pending entry for that domain is rejected (see below) — otherwise the very next mention would immediately re-stage the same rejected request.

### Rejecting a proposal

`pending.py reject <id>` never deletes the entry — it stamps `rejected_at` and keeps it on disk as history (`pending.py list` hides it by default, `pending.py list --all` shows it). It also zeros the mention counter for that domain in `domain_mentions.json`, so `detect_domain_recurrence.py` requires `min_mentions` fresh mentions before it stages that domain again, instead of re-asking on the very next prompt. An already-rejected entry can't be approved (`pending.py approve` refuses it) — a genuinely changed mind stages a new request instead.

### Staleness detection

`detect_staleness.py` (Stop hook) catches the opposite failure mode from domain recurrence: a domain that already has a skill, whose files got edited this session, but whose skill was never actually invoked via the `Skill` tool — a sign the skill might be missing the workflow that was just used. It reads the whole session transcript (every turn, not just the last one) for `Skill` tool invocations and `Edit`/`Write`/`NotebookEdit` file paths, maps edited paths to domains with the same auto-discovery `detect_domain_recurrence.py` uses, and stages a `patch` request (reusing an existing non-rejected one if present) the same content-free way. It never proposes `create` — only `patch`, since the skill already exists.

## Claude Code (reference implementation)

Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/detect_complexity.py" },
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/detect_pending_completion.py" },
        { "type": "command", "command": "python3 .claude/skills/autodidact/scripts/detect_staleness.py" }
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
