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

STOPWORDS = {
    "a", "agora", "ainda", "ajuda", "ali", "and", "antes", "ao", "aonde", "aos", "aqui", "aquilo", "are", "arquivo", "as", "ate", "atualmente", "cada", "codigo", "coesao", "com", "como", "criar", "cuja", "cujo", "da", "dar", "das", "de", "depois", "dizer", "do", "dos", "e", "ela", "elas", "ele", "eles", "em", "entao", "essa", "esse", "esta", "estar", "este", "fala", "falando", "falar", "fazer", "foi", "foobar", "fooservice", "for", "from", "has", "have", "hello", "hoje", "integra", "integracao", "integrar", "interna", "isso", "ja", "lhe", "mais", "mas", "mesma", "mesmo", "meu", "meus", "minha", "muito", "na", "nas", "no", "nos", "nova", "novamente", "novas", "novo", "o", "onde", "ontem", "os", "ou", "outra", "outras", "outro", "outros", "para", "por", "pouco", "precisa", "precisamos", "preciso", "product", "projeto", "quais", "qual", "quando", "quanto", "quantos", "que", "quem", "queremos", "quero", "sao", "se", "ser", "service", "skill", "so", "sobre", "tambem", "tarefa", "task", "tem", "ter", "test", "teste", "that", "the", "this", "toda", "todas", "todo", "todos", "um", "uma", "usar", "vamos", "ver", "voc", "voce", "voces", "vos", "was", "with", "world",
}

DEFAULT_CONFIG = {
    "min_mentions": 3,
    "excluded_domains": [],
}


def get_excluded_domains(config):
    vals = set()
    for v in config.get("excluded_domains", []):
        if isinstance(v, str):
            vals.add(v.lower())
        elif isinstance(v, dict):
            vals.update(str(x).lower() for x in v.values())
    return vals

def extract_candidates(prompt_text):
    import re as _re
    # Hook payload may include injected context, pasted data, or code. Only
    # inspect the user's plain text and terms named as an integration/domain.
    text = _re.sub(r"<system-reminder.*?</system-reminder>|<pasted_content[^>]*>.*?</pasted_content>|```.*?```", " ", prompt_text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r"\[[^\]]*compressed[^\]]*\]", " ", text, flags=_re.IGNORECASE)
    matches = []
    patterns = (
        r"(?:integrar|integração|integracao|usar|conectar|conexão|conexao|sobre|skill|api)\s+(?:com\s+)?([a-z0-9]+(?:-[a-z0-9]+)*)",
        r"\b([a-z0-9]+(?:-[a-z0-9]+)*)\s+(?:api|integração|integracao|skill)\b",
    )
    for pattern in patterns:
        matches.extend(_re.findall(pattern, text.lower()))
    return [t for t in dict.fromkeys(matches) if len(t) >= 4 and t not in STOPWORDS and not t.isdigit() and not _re.match(r"^(cu-|d\d+$)", t)]

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
        if (
            manifest.get("target_skill") == target
            and manifest.get("action") == "create"
            and not manifest.get("rejected_at")
        ):
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
    excluded = get_excluded_domains(config)
    candidates = extract_candidates(prompt_text)
    if not candidates:
        return
    # deduplicate while preserving order
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    mentions = load_mentions()
    for domain in uniq:
        if domain in excluded:
            continue
        if skill_exists(domain):
            # skill already exists — don't track
            if domain in mentions:
                del mentions[domain]
            continue
        mentions[domain] = mentions.get(domain, 0) + 1
        count = mentions[domain]
        if count < min_mentions:
            continue
        existing = existing_pending_id(domain)
        if existing:
            # reuse pending — just remind
            save_mentions(mentions)
            print(
                "autodidact: '{}' mentioned {} time(s) with no skill — request {} queued. "
                "Ask approval at task end, then invoke skill-creator."
                .format(domain, count, existing)
            )
            continue
        entry_id = stage_request(domain)
        save_mentions(mentions)
        if entry_id:
            config2 = get_config()
            if config2.get("auto_approve"):
                print(
                    "autodidact: '{}' mentioned {} time(s); create request {} auto-approved. "
                    "Invoke skill-creator after the current task; write .claude/skills/{}/."
                    .format(domain, count, entry_id, domain)
                )
            else:
                print(
                    "autodidact: '{}' mentioned {} time(s) with no skill — request {} queued. "
                    "Ask approval at task end, then invoke skill-creator."
                    .format(domain, count, entry_id)
                )
        else:
            save_mentions(mentions)
            print(
                "autodidact: '{}' mentioned {} time(s) with no skill and staging failed "
                "(pending.py new errored) — run 'python3 .claude/skills/autodidact/scripts/"
                "pending.py new --action create --target {}' yourself and ask the user "
                "to approve.".format(domain, count, domain)
            )
            continue
    save_mentions(mentions)

if __name__ == "__main__":
    main()
