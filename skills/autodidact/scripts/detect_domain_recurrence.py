#!/usr/bin/env python
"""UserPromptSubmit hook: detect repeated questions about a domain lacking a skill.

Reads the hook JSON payload from stdin (Claude Code's UserPromptSubmit event),
extracts the user prompt, identifies referenced integration/domain names, and
tracks per-domain mention counts in .state/domain_mentions.json.

When a domain accumulates >= min_mentions without a corresponding skill directory,
emits a reminder nudging autodidact evaluation for that domain.

Fires on every mention once the domain has reached min_mentions (insistent, not
just at multiples) until the skill is created. When a skill is detected, resets
the counter for that domain.
"""
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(SCRIPT_DIR, "..")
STATE_DIR = os.path.join(SKILL_DIR, ".state")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
MENTIONS_PATH = os.path.join(STATE_DIR, "domain_mentions.json")

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
    path = os.path.normpath(os.path.join(SKILL_DIR, "..", skill_name))
    return os.path.isdir(path)


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
        print(
            "autodidact: '{}' mentioned {} time(s) with no .claude/skills/{}/ — "
            "this is not optional, stage a create/patch proposal via pending.py "
            "before ending this turn (write_approval still gates the actual write).".format(
                domain, count, domain
            )
        )


if __name__ == "__main__":
    main()
