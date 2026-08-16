---
disable-model-invocation: true
description: 'Health report for the skills in .claude/skills/ — stale, bloated, unmeasured, orphaned, structurally invalid, and pairs that are candidates for consolidation. Read-only: reports and proposes, never edits or removes a skill.'
argument-hint: '[cutoff days for "stale" | skill name to focus on]'
allowed-tools: [
  'Read',
  'Glob',
  'Grep',
  'Bash(ls:*)',
  'Bash(wc:*)',
  'Bash(git log:*)',
  'Agent',
  'TodoWrite'
]
---

Maintenance pass over the skill library. The problem it exists to catch: a library
that only ever grows accumulates narrow near-duplicates, and each one costs triggering
accuracy for its siblings plus tokens in every session's skill index.

**Read-only. Never edit, move, archive, or delete a skill.** Output is a ranked list
of proposals for the user to accept. The repo is versioned in git, so there is no need
for an archive folder or backups — that is what `git log` and `git revert` are for.

## Known limitation — state it in the report

There is typically **no usage telemetry** for skills: nothing records that a skill
actually fired in a real session. So "stale" below means *not modified in N days*,
which is a proxy for abandonment, not for uselessness — a stable, correct,
frequently-firing skill also stops being edited. Never present a stale skill as
unused; present it as "not touched since `<date>`, worth confirming it is still
accurate". Saying this plainly is the point: a report that overstates its own
evidence gets acted on wrongly.

## Signals to collect

Scope: every `.claude/skills/*/SKILL.md`. Run the collection in parallel — these are
independent.

| Signal | How to measure | Why it matters |
| --- | --- | --- |
| **Stale** | `git log -1 --format=%ad --date=short -- <skill>/SKILL.md`, compare to the cutoff (`$ARGUMENTS` in days, default 180) | Documentation drifts from the code it describes. |
| **No eval** | absence of `<skill>/evals/` (or your `skill-creator`'s equivalent) | The `description` is the whole triggering mechanism. Unmeasured means unknown. |
| **Long description** | character count of the `description` field | The skill index loads every description every session. Long ones cost tokens permanently and may truncate. |
| **Bloated SKILL.md** | `wc -l <skill>/SKILL.md` over ~500 | Beyond that, content usually belongs in `references/`. |
| **Invalid** | frontmatter/structure check, via your `skill-creator`'s validator if it has one | Catches broken frontmatter, stray `<`/`>` in the description, loose `.md` files at the skill root. |
| **Orphaned** | `Grep` for the skill name across `.claude/commands/` and other `.claude/skills/*/SKILL.md` | A skill nothing points at relies purely on its own triggering — fine if measured, a smell if not. |
| **Duplicate candidate** | trigger terms shared between two descriptions | Two skills competing for the same prompt is the failure mode this whole command exists to catch. |

For the duplicate pass, read all the descriptions and group by domain. Within a
group, flag pairs whose triggers overlap. This is judgment, not string matching —
siblings can legitimately share vocabulary while staying mutually exclusive.

If `$ARGUMENTS` names a skill instead of a number, run every signal against just that
one and skip the ranking.

## What to propose (and what to never propose)

Per flagged skill, exactly one proposal:

- **Confirm** — stale but probably still right: name the file/integration it
  documents so the user can check in one look.
- **Measure** — no eval: propose an eval-set, don't run it here (that's your
  `skill-creator`'s job and it costs model calls).
- **Shorten / split** — oversized description or body.
- **Fix** — a validator failure, with the exact error.
- **Consolidate** — two overlapping skills: say which absorbs which and what the
  merged boundary would be.

Never propose deleting a skill on staleness alone — without usage data that inference
is not available, and this is exactly where the missing telemetry bites.

## Output

Report ranked most-actionable first, one line per finding — a long report nobody
reads is worse than a short one that gets acted on.

```markdown
# Skill curation — {N} skills analyzed

## Summary
- Stale (> {cutoff} days): {n} | No eval: {n} | Invalid: {n} | Orphaned: {n} | Duplicate candidates: {n} pairs

## Findings
| Skill | Signal | Proposal | Detail |
| --- | --- | --- | --- |
| `{name}` | {signal} | {Confirm/Measure/Shorten/Fix/Consolidate} | {evidence: date, count, error} |

## Consolidation candidates
{pair -> which absorbs which -> what the boundary would be. If none: "No relevant overlap".}

## Caveat
No usage telemetry: "stale" = not modified since the date cited, NOT = unused.
```

Close by offering to act on the accepted items via `/skill-learn` or `/skill-fork` —
this command does not carry them out itself.
