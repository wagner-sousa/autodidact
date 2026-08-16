---
disable-model-invocation: true
description: 'Forks a skill from a URL (Anthropic, OpenAI, Hermes, or any agentskills.io-compatible repo) into the project skills directory — evaluates fit, strips dead weight, applies project conventions, stamps provenance, and checks the trigger before writing.'
argument-hint: '[skill URL: GitHub tree, raw SKILL.md, or repo/path]'
allowed-tools: [
  'Read',
  'Glob',
  'Grep',
  'WebFetch',
  'Write',
  'Edit',
  'Bash(ls:*)',
  'Bash(grep:*)',
  'Skill',
  'TodoWrite'
]
---

The user wants to fork the external skill at `$ARGUMENTS` into this project.

**Load a `skill-creator` skill first, if the project has one.** It should own the
authoring flow and any project-specific conventions. See
[SKILL_CREATOR.md](../skills/autodidact/SKILL_CREATOR.md) for how to fork or build one
— Anthropic's (https://github.com/anthropics/skills/tree/main/skills/skill-creator)
and OpenAI's (https://github.com/openai/skills/blob/main/skills/.system/skill-creator)
implementations are good starting points. This command only decides *whether and how*
an EXTERNAL skill enters the repo — it does not restate authoring rules that belong to
`skill-creator`.

## Flow

1. `TodoWrite` with phases: Fetch, Evaluate fit, Fork, Clean, Conventions, Check
   trigger, Approval.

2. **Fetch.** From a GitHub `tree`/`blob` URL derive the raw path
   (`raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>`). `WebFetch` the
   `SKILL.md`; enumerate `references/`/`scripts/`/`assets/` via
   `api.github.com/repos/<owner>/<repo>/contents/<path>`.

3. **Evaluate fit — report a verdict (fork / adapt / skip) BEFORE writing anything.**
   - Stack: check whether the skill's stack/tooling assumptions match this project.
     A skill written for a different platform or product usually does NOT work as-is.
   - Overlap: `grep` in `.claude/skills/` — if an existing skill already owns the
     topic, PREFER patching it over creating a duplicate (autodidact's own rule).
   - Value: only fork what pays for its own context cost.

4. **Fork.** Create `.claude/skills/<name>/` (hyphen-case, <64 chars, folder name ==
   skill name). Copy `SKILL.md` plus the relevant `references/`/`scripts/`.

5. **Clean dead weight**: remove platform-specific files that don't apply here
   (`agents/openai.yaml`, `README`, `INSTALLATION_GUIDE`, `QUICK_REFERENCE`,
   `CHANGELOG`, or anything tied to the source platform's own tooling).

6. **Stamp provenance** at the top of the body (right after the title), so a future
   upstream merge stays diffable:
   ```
   > **Fork — <owner>/<repo> @ <ref>** (`<upstream path>`), kept in this repo.
   > Customizations vs upstream (reapply on merge): [references/fork-customizations.md](references/fork-customizations.md).

   > The rest of this file is the upstream guide.
   ```

7. **Apply project conventions** (whatever your `skill-creator` documents: language,
   description format, trigger style, section order). Record EVERY deviation from
   upstream in `references/fork-customizations.md`.

8. **Check the trigger.** If your `skill-creator` has an eval harness, write a small
   query set (positives plus the siblings it could collide with) and measure. Iterate
   the description until it reliably fires (or record the ceiling honestly).

9. **Test any embedded scripts by running them** — they may assume the upstream
   environment; adapt or remove what doesn't apply.

10. **Ask for approval before writing.** Show: the fit verdict, what changes vs
    upstream, and the description (with its measured score if available).

## Output

- **Source**: repo@ref, file.
- **Verdict**: fork / adapt / skip, and why.
- **Changes vs upstream**: summary of `fork-customizations.md`.
- **Trigger**: score if measured, model used, known ceiling (an honest caveat beats a
  rounded-up number).
- **Files**: what will be written, before writing.
