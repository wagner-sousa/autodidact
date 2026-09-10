#!/usr/bin/env python
"""UserPromptSubmit hook: detect repeated questions about a domain lacking a skill.

Reads the hook JSON payload from stdin (Claude Code's UserPromptSubmit event),
extracts the user prompt, identifies referenced integration/domain names, and
tracks per-domain mention counts in .state/domain_mentions.json.

When a domain accumulates >= min_mentions without a corresponding skill
directory, this script:
  1. Calls pending.py new --action create --target <domain> to queue a request
     (manifest only, no content — safe to call without user confirmation).
  2. Prints an instruction for the agent to use AskUserQuestion to ask the user
     whether to approve the staged request now, reject it, or decide later.

If a pending entry for this target already exists (awaiting approval or
skill-creator), skips staging a duplicate and just prints the reminder.

This script never generates skill content and never calls approve — content
generation is skill-creator's job, approval is the user's decision.

Fires on every mention once the domain has reached min_mentions (insistent,
not just at multiples) until the skill is created. When a skill is detected,
resets the counter for that domain.
"""
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(SCRIPT_DIR, "..")
STATE_DIR = os.path.join(SKILL_DIR, ".state")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
MENTIONS_PATH = os.path.join(STATE_DIR, "domain_mentions.json")
PENDING_DIR = os.path.join(STATE_DIR, "pending")
PENDING_SCRIPT = os.path.join(SCRIPT_DIR, "pending.py")
SKILLS_ROOT = os.path.join(SKILL_DIR, "..")

DEFAULT_CONFIG = {
    "min_mentions": 3,
    "known_domains": [],
}


def get_integration_dir():
    """Walk up from the skill dir to find the project's Integration directory.

    Assumes standard layout: <project>/.claude/skills/autodidact/
    Resolves to: <project>/src/Uoou/Component/Integration/ when present.
    Override by setting known_domains in config.json.
    """
    candidate = os.path.normpath(
        os.path.join(SKILL_DIR, "..", "..", "..", "src", "Uoou", "Component", "Integration")
    )
    return candidate if os.path.isdir(candidate) else None


def split_camel_case(name):
    """Split a CamelCase name into lowercase words (AzulCargo -> ['azul', 'cargo'])."""
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", name)
    return [w.lower() for w in words if w]


def get_known_domains(config):
    """Return {search_pattern: skill_dir_name} from Integration dir + config list.

    Integration dir: subdir names have version suffixes stripped (e.g. BlingV3 ->
    bling, Correios -> correios), then are split on CamelCase word boundaries so
    the regex matches the name whether written solid, spaced, or hyphenated
    (AzulCargo -> matches "azulcargo", "azul cargo", "azul-cargo"). The resulting
    skill_dir_name is kebab-case (AzulCargo -> azul-cargo).

    Config known_domains accepts a list of strings or {term: skill_name} dicts
    for domains not discoverable from the Integration dir.
    """
    domains = {}

    integration_dir = get_integration_dir()
    if integration_dir:
        for entry in os.listdir(integration_dir):
            if os.path.isdir(os.path.join(integration_dir, entry)):
                name = re.sub(r"[Vv]\d+$", "", entry)
                words = split_camel_case(name)
                if words:
                    pattern = r"[\s-]*".join(re.escape(w) for w in words)
                    domains[pattern] = "-".join(words)

    for item in config.get("known_domains", []):
        if isinstance(item, str):
            domains[re.escape(item.lower())] = item.lower()
        elif isinstance(item, dict):
            for term, skill_name in item.items():
                domains[re.escape(str(term).lower())] = str(skill_name).lower()

    return domains


def skill_exists(skill_name):
    path = os.path.normpath(os.path.join(SKILLS_ROOT, skill_name))
    return os.path.isdir(path)


def skill_creator_available():
    return os.path.isdir(os.path.join(SKILLS_ROOT, "skill-creator"))


def existing_pending_id(target):
    """Return the id of an already-staged, non-rejected entry for target, or None."""
    if not os.path.isdir(PENDING_DIR):
        return None
    for entry_id in os.listdir(PENDING_DIR):
        manifest_path = os.path.join(PENDING_DIR, entry_id, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, ValueError):
            continue
        if manifest.get("target_skill") == target and manifest.get("action") == "create":
            return entry_id
    return None


def stage_request(target):
    """Call pending.py new --action create --target <target>, return the new id or None."""
    try:
        result = subprocess.run(
            [sys.executable or "python3", PENDING_SCRIPT, "new",
             "--action", "create", "--target", target],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


def load_mentions():
    if os.path.exists(MENTIONS_PATH):
        try:
            with open(MENTIONS_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def save_mentions(mentions):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MENTIONS_PATH, "w") as f:
        json.dump(mentions, f, indent=2)


def get_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                raw = json.load(f)
            cfg.update(raw.get("domain_recurrence", {}))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return cfg


def detect_domains(prompt_text, known_domains):
    """Return set of skill_dir_names referenced in prompt_text."""
    found = set()
    prompt_lower = prompt_text.lower()
    for pattern, skill_name in known_domains.items():
        if re.search(r"(?<![a-z])" + pattern + r"(?![a-z])", prompt_lower):
            found.add(skill_name)
    return found


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    prompt_text = payload.get("prompt", "")
    if not prompt_text:
        return

    config = get_config()
    min_mentions = int(config.get("min_mentions", DEFAULT_CONFIG["min_mentions"]))
    known_domains = get_known_domains(config)

    if not known_domains:
        return

    detected = detect_domains(prompt_text, known_domains)
    if not detected:
        return

    mentions = load_mentions()
    to_remind = []

    for domain in detected:
        if skill_exists(domain):
            mentions.pop(domain, None)
            continue

        count = mentions.get(domain, 0) + 1
        mentions[domain] = count

        if count >= min_mentions:
            to_remind.append((domain, count))

    save_mentions(mentions)

    for domain, count in to_remind:
        entry_id = existing_pending_id(domain)
        if entry_id is None:
            entry_id = stage_request(domain)

        if entry_id:
            print(
                "autodidact: '{}' mentioned {} time(s) with no skill — a create request "
                "is queued (id {}). At the END of your current task/response, use "
                "AskUserQuestion to ask: approve (then invoke skill-creator to draft it "
                "directly under .claude/skills/{}/), reject, or decide later. If the "
                "user picks 'decide later', this request will surface again on the next "
                "mention of '{}'. Don't ask mid-task; finish what the user asked "
                "first.".format(domain, count, entry_id, domain, domain)
            )
        else:
            print(
                "autodidact: '{}' mentioned {} time(s) with no skill and staging failed "
                "(pending.py new errored) — run 'python3 .claude/skills/autodidact/scripts/"
                "pending.py new --action create --target {}' yourself and ask the user "
                "to approve.".format(domain, count, domain)
            )


if __name__ == "__main__":
    main()
