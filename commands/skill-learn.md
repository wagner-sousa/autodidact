---
disable-model-invocation: true
description: 'Turns what was just discovered into a skill — distills a reusable procedure from the current conversation (default), a directory, a URL, or pasted notes, drafts it, checks the trigger, and asks for approval before writing.'
argument-hint: '[source: empty = this conversation | path | URL | notes]'
allowed-tools: [
  'Read',
  'Glob',
  'Grep',
  'WebFetch',
  'Write',
  'Edit',
  'Bash(ls:*)',
  'Bash(git log:*)',
  'Skill',
  'TodoWrite'
]
---

The user wants a reusable skill distilled from `$ARGUMENTS`. Answer the question this
command exists for: *the work is done, what did we learn that shouldn't be re-derived
next time?*

**Load a `skill-creator` skill first, if the project has one.** It should own the
authoring flow (draft -> test -> review) and any project-specific conventions. See
[SKILL_CREATOR.md](../skills/autodidact/SKILL_CREATOR.md) for how to fork or build one.
This command only decides *what* becomes a skill and *where the material comes from* —
it does not restate authoring rules that belong to `skill-creator`.

## Source

Read `$ARGUMENTS` and pick the source. Empty argument is the common case and means
**this conversation**.

| Argument | Source | How to collect |
| --- | --- | --- |
| (empty) | the current conversation | Reread the session: the tool calls made, the dead ends, the corrections the user made, the final working answer. |
| directory/file path | the code | `Glob` + `Read`. |
| URL | external doc | `WebFetch`. |
| free text | pasted notes | The argument itself. |

Several sources can combine ("`/skill-learn` what we did + the vendor's doc") — collect
each, then distill once.

## What becomes a skill (and what doesn't)

Worth capturing when a future task would otherwise repeat the same exploration:

- A **non-obvious procedure** — the sequence only works in a specific order, or one
  step has a trap that cost time here.
- **Reverse engineering** — undocumented behavior of an integration, API, queue, or
  legacy code, discovered by reading/testing.
- A **correction the user made** — you did it one way, the user said "not like that,
  like this". That correction is the highest-signal material there is, because it
  encodes a preference the code does not state.
- A **recurring diagnosis** — the symptom-to-cause map for a class of bug.

Doesn't become a skill (say so and stop, rather than producing filler):

- What the code already says and a single search/read call finds.
- A one-off fix with no reusable rule behind it.
- Something an existing skill already covers — in that case the outcome is a **patch
  to that skill**, not a new one. Check first: read the descriptions of the skills in
  `.claude/skills/` and say which one is the natural home.

Deciding between new skill and patch is the main judgment call here. Prefer patching:
a near-duplicate skill costs triggering accuracy for both siblings.

## Flow

1. `TodoWrite` with the phases: Collect source, Decide (new vs patch vs nothing),
   Draft, Check trigger, Approval.
2. Collect the source per the table above.
3. **Decide and state the decision before writing anything**: new skill `<name>`,
   patch to skill `<name>`, or nothing worth capturing (with the reason).
4. Draft following your `skill-creator`'s conventions if you have one installed;
   otherwise use the agentskills.io SKILL.md baseline (frontmatter with `name` +
   `description`, a body with clear sections).
5. If your `skill-creator` has an eval harness, measure triggering with it before
   finalizing the description. A description that was not measured is a guess.
6. **Ask for approval, then write.** Autodidact's own pending-queue convention
   (`write_approval` in `skills/autodidact/config.json`) already gates this — route
   the proposal through `pending.py new` rather than writing directly. Show: the
   `description`, the section outline, and the diff if it is a patch.
7. After approval (or immediately if `write_approval` is `false`), the files land in
   `.claude/skills/`.

## Output

Report:

- **Source**: what was read.
- **Decision**: new skill / patch to `<name>` / nothing to capture, and why.
- **Trigger**: score if measured, and any known ceiling (an honest caveat is worth
  more than a rounded-up number).
- **Files**: what will be written, before writing.
