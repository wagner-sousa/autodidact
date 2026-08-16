# Pairing autodidact with a skill-creator

Autodidact's guard step (see `SKILL.md` → "Skill guard") reviews every drafted skill against a `skill-creator` skill before staging it. Autodidact does not bundle a `skill-creator` itself — it is a separate, actively-maintained skill you fork or write once per project, and reuse across every autodidact proposal. Any `skill-creator` that authors [agentskills.io](https://agentskills.io)-compliant `SKILL.md` files works here, regardless of which agent it was originally written for.

## Fork an existing skill-creator

Two well-maintained implementations to start from:

- **Anthropic**: https://github.com/anthropics/skills/tree/main/skills/skill-creator — an interactive draft → test → review → improve flow for authoring `SKILL.md` files, with `references/` covering frontmatter conventions, scoping guidance, and description quality.
- **OpenAI**: https://github.com/openai/skills/blob/main/skills/.system/skill-creator — a comparable creator skill from OpenAI's skills repo, useful as a second reference point or if your workflow leans on OpenAI-flavored tooling.

Recommended approach:

1. Copy one of the two into `.claude/skills/skill-creator/` (or your project's equivalent skills path).
2. Keep a short provenance note in the copy (e.g. `references/upstream.md`) recording which repo/commit it was forked from, so future updates can be diffed against upstream instead of drifting silently.
3. Layer your own project conventions on top (naming rules, required frontmatter fields, where skills are allowed to live, approval process) without rewriting the upstream draft/test/review flow itself.
4. Re-sync periodically by diffing your fork against the upstream repo and pulling in fixes.

## Or write your own

If neither upstream implementation fits, a minimal `skill-creator` only needs to be able to:

1. Take a description of a workflow and draft a `SKILL.md` (frontmatter + body) for it.
2. Validate structure: required frontmatter fields present, description length/quality, no orphaned reference files, scope is neither too broad (competes with existing skills) nor too narrow (one-off).
3. Report pass/fail with concrete fixes — this is the contract autodidact's guard step relies on (see `SKILL.md`'s "Skill guard" section: a subagent runs your `skill-creator`'s review against a drafted skill and reports back).

## If you skip skill-creator entirely

Autodidact still works without one — the guard step in `SKILL.md` explicitly says to skip validation rather than block the proposal when no `skill-creator` is installed. You lose the structural-review safety net, but the propose/stage/approve loop still functions.
