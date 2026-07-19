#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Permission Lens — Tier 1 static analyzer for Claude Code permission dialogs.

Entry point for the `PermissionRequest` hook. Reads the pending permission
request from stdin, produces a plain-language explanation + risk assessment, and
prints it as `{"systemMessage": "..."}` on stdout. It NEVER returns a decision
field, so the native permission dialog always shows — augmenting the human's
judgment, not replacing it.

Correctness invariants (see NOTES.md for the doc sections these come from):
  * Exactly one JSON object is printed to stdout, on every code path.
  * The script exits 0 on every code path. On `PermissionRequest`, exit 2 would
    DENY the permission, so any failure fails OPEN: print `{}` and exit 0.
  * No `hookSpecificOutput` / `decision` is ever emitted.

This project studied dyad-sh/dyad `.claude/hooks/` (Apache-2.0) for stdin
handling and shell-metacharacter patterns; no code was copied or adapted.
"""
import json
import os
import re
import shlex
import sys
import traceback
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - exercised only when pyyaml is missing
    yaml = None

# Tier 1 budget target: analysis must stay well under 50ms. See tests/test_performance.py.
MAX_MESSAGE_CHARS = 500  # M1: hardcoded. Becomes config in M2 (see plan / brief).
LANG = "en"              # M1: hardcoded. `config.json` "lang": "zh"|"en" lands in M2.

RULES_PATH = Path(__file__).with_name("rules.yaml")

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
SEVERITY_LABEL = {
    "en": {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"},
    "zh": {"high": "高", "medium": "中", "low": "低"},
}
INFO_EMOJI = "ℹ️"
RISK_LABEL = {"en": "Risk", "zh": "风险"}


# ── command parsing (conservative; not a full bash grammar) ───────────────────

# Top-level statement separators and pipeline separators. We split with a
# quote-aware scanner rather than a regex so quoted separators are ignored.
_STATEMENT_SEPS = {";", "\n"}
_TWO_CHAR_OPS = {"&&", "||"}


class Parsed:
    """Best-effort structural view of a shell command string."""

    def __init__(self, command):
        self.command = command
        self.has_command_sub = bool(re.search(r"\$\(", command))
        self.has_backtick = "`" in command
        self.has_process_sub = bool(re.search(r"[<>]\(", command))
        # Pipeline stages across every statement, including the bodies of
        # $(...) / `...` / <(...) so `bash <(curl ...)` and `$(curl ... | sh)`
        # are analyzed too.
        self.stages = []
        self.simple_commands = []  # list[SimpleCommand]
        for chunk in _iter_command_chunks(command):
            for stage in _split_pipeline(chunk):
                stage = stage.strip()
                if stage:
                    self.stages.append(stage)
                    self.simple_commands.append(SimpleCommand(stage))

    @property
    def first_stage(self):
        return self.stages[0] if self.stages else ""


class SimpleCommand:
    """A single pipeline stage tokenized best-effort into argv."""

    def __init__(self, raw):
        self.raw = raw
        try:
            # posix=True expands quotes but keeps $VAR text literally, which is
            # what we want for target-risk analysis.
            self.argv = shlex.split(raw, posix=True)
        except ValueError:
            self.argv = raw.split()
        # Skip leading `VAR=value` assignments and env/wrappers to find the verb.
        self.name = ""
        for tok in self.argv:
            if "=" in tok and re.match(r"^\w+=", tok):
                continue
            self.name = os.path.basename(tok)
            break

    def flags_and_args(self):
        """argv after the command name, split into (flag tokens, positional args)."""
        seen_name = False
        flags, args = [], []
        for tok in self.argv:
            if not seen_name:
                if "=" in tok and re.match(r"^\w+=", tok):
                    continue
                seen_name = True
                continue
            (flags if tok.startswith("-") else args).append(tok)
        return flags, args


def _iter_command_chunks(command):
    """Yield the top-level statement text plus any substitution bodies.

    Substitution bodies are extracted with tolerant regexes and yielded so their
    inner commands get parsed as ordinary statements.
    """
    yield from _split_statements(command)
    for body in re.findall(r"\$\(([^()]*)\)", command):
        yield from _split_statements(body)
    for body in re.findall(r"`([^`]*)`", command):
        yield from _split_statements(body)
    for body in re.findall(r"[<>]\(([^()]*)\)", command):
        yield from _split_statements(body)


def _split_statements(text):
    """Quote-aware split on ; & newline && ||. Returns a list of statement strings."""
    return _scan_split(text, split_pipe=False)


def _split_pipeline(text):
    """Quote-aware split of one statement into pipeline stages on `|`."""
    return _scan_split(text, split_pipe=True, pipes_only=True)


def _scan_split(text, split_pipe=False, pipes_only=False):
    parts = []
    buf = []
    quote = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        two = text[i:i + 2]
        if pipes_only:
            # Split on a single | but not || (that's a statement separator).
            if ch == "|" and two != "||":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        else:
            if two in _TWO_CHAR_OPS:
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if ch in _STATEMENT_SEPS or ch == "&":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


# ── predicates (for rules regex can't express cleanly) ────────────────────────

_RECURSIVE_RE = re.compile(r"(^|(?<=[\s-]))(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b", re.IGNORECASE)
_RISKY_TARGET_RE = re.compile(r"(\$\{?\w|[*?\[]|(^|\s)(/|~)($|\s|/))")


def _rm_commands(parsed):
    return [sc for sc in parsed.simple_commands if sc.name == "rm"]


def _rm_is_recursive(sc):
    flags, _ = sc.flags_and_args()
    return any(_RECURSIVE_RE.search(f) for f in flags)


def _rm_targets(sc):
    _, args = sc.flags_and_args()
    return args


def _target_is_risky(target):
    # Variable expansion, a glob, or an absolute/home root — the cases where an
    # rm -r can delete far more than the literal path suggests.
    if re.search(r"\$\{?\w", target):
        return True
    if any(g in target for g in "*?[") :
        return True
    stripped = target.strip("'\"")
    if stripped in ("/", "~", "/*", "~/") or stripped.startswith(("/", "~/")):
        return True
    return False


def pred_rm_recursive_risky_target(parsed):
    for sc in _rm_commands(parsed):
        if _rm_is_recursive(sc) and any(_target_is_risky(t) for t in _rm_targets(sc)):
            return True
    return False


def pred_rm_recursive_plain(parsed):
    for sc in _rm_commands(parsed):
        if not _rm_is_recursive(sc):
            continue
        targets = _rm_targets(sc)
        if targets and not any(_target_is_risky(t) for t in targets):
            return True
    return False


PREDICATES = {
    "rm_recursive_risky_target": pred_rm_recursive_risky_target,
    "rm_recursive_plain": pred_rm_recursive_plain,
}


# ── rule engine ───────────────────────────────────────────────────────────────

_RULES_CACHE = None


def load_rules():
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    if yaml is None:
        _RULES_CACHE = []
        return _RULES_CACHE
    with open(RULES_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    rules = []
    for raw in data.get("rules", []):
        compiled = None
        if raw.get("regex"):
            compiled = re.compile(raw["regex"])
        rules.append({
            "id": raw["id"],
            "category": raw.get("category", ""),
            "severity": raw.get("severity", "low"),
            "regex": compiled,
            "predicate": raw.get("predicate"),
            "scope": raw.get("scope", "whole"),
            "explanation": {"en": raw.get("explanation_en", ""), "zh": raw.get("explanation_zh", "")},
            "risk": {"en": raw.get("risk_en", ""), "zh": raw.get("risk_zh", "")},
        })
    _RULES_CACHE = rules
    return rules


def analyze(parsed, rules=None):
    """Return matched rules, highest severity first, deduped by rule id."""
    rules = rules if rules is not None else load_rules()
    matches = []
    for rule in rules:
        if _rule_matches(rule, parsed):
            matches.append(rule)
    matches.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 0), reverse=True)
    return matches


def _rule_matches(rule, parsed):
    if rule["predicate"]:
        fn = PREDICATES.get(rule["predicate"])
        return bool(fn and fn(parsed))
    regex = rule["regex"]
    if not regex:
        return False
    if rule["scope"] == "segment":
        return any(regex.search(stage) for stage in parsed.stages)
    return bool(regex.search(parsed.command))


# ── neutral "what it does" summary ────────────────────────────────────────────

# Verb phrasing for common commands, so a no-risk-match dialog still gets a line.
_VERB_PHRASES = {
    "ls": "Lists directory contents",
    "cat": "Prints file contents",
    "cd": "Changes the working directory",
    "cp": "Copies files",
    "mv": "Moves or renames files",
    "mkdir": "Creates a directory",
    "touch": "Creates or updates a file timestamp",
    "echo": "Prints text",
    "grep": "Searches text",
    "rg": "Searches text (ripgrep)",
    "find": "Searches the filesystem",
    "sed": "Edits a text stream",
    "awk": "Processes text",
    "python": "Runs a Python program",
    "python3": "Runs a Python program",
    "node": "Runs a Node.js program",
    "make": "Runs a make target",
    "brew": "Runs a Homebrew command",
    "docker": "Runs a Docker command",
    "kubectl": "Runs a kubectl command",
}
_SUBCOMMAND_TOOLS = {"git", "npm", "pnpm", "yarn", "docker", "kubectl", "cargo", "go", "pip", "pip3", "brew", "gh"}


def neutral_summary(parsed):
    sc = parsed.simple_commands[0] if parsed.simple_commands else None
    if not sc or not sc.name:
        return "Runs a shell command"
    name = sc.name
    _, args = sc.flags_and_args()
    if name in _SUBCOMMAND_TOOLS and args:
        return f"Runs: {name} {args[0]}"
    if name in _VERB_PHRASES:
        return _VERB_PHRASES[name]
    return f"Runs `{name}`"


# ── message formatting ────────────────────────────────────────────────────────

def format_message(parsed, matches, lang=LANG, max_chars=MAX_MESSAGE_CHARS):
    if not matches:
        return _truncate(f"{INFO_EMOJI} {neutral_summary(parsed)}", max_chars)

    top = matches[0]
    sev = top["severity"]
    emoji = SEVERITY_EMOJI.get(sev, INFO_EMOJI)
    label = SEVERITY_LABEL[lang].get(sev, sev.upper())
    lines = [
        f"{emoji} {label} · {top['explanation'][lang]}",
        f"{RISK_LABEL[lang]}: {top['risk'][lang]}",
    ]
    # Up to two additional distinct risks (dedupe by category to avoid near-dupes).
    seen = {top["category"]}
    extras = 0
    for rule in matches[1:]:
        if rule["category"] in seen:
            continue
        seen.add(rule["category"])
        e = SEVERITY_EMOJI.get(rule["severity"], INFO_EMOJI)
        lines.append(f"{e} {rule['explanation'][lang]}")
        extras += 1
        if extras == 2:
            break
    return _truncate("\n".join(lines), max_chars)


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + "…"


# ── M4 extension point (no-op in M1–M3) ───────────────────────────────────────

def notify(payload):
    """Stub for the future companion localhost panel (milestone M4).

    A later `notify_url` config key will POST the pending request here so a web
    page can render a richer breakdown. Intentionally does nothing today.
    """
    return None


# ── entry point ───────────────────────────────────────────────────────────────

def build_message(event):
    """Pure core: event dict -> systemMessage string (or None to stay silent)."""
    # PermissionRequest input schema — see NOTES.md ("Confirmed facts", item 1):
    # tool_name + tool_input{command,...}. Matcher is Bash, but guard anyway.
    if event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command")
    if not command or not command.strip():
        return None
    parsed = Parsed(command)
    matches = analyze(parsed)
    notify({"command": command, "matches": [m["id"] for m in matches]})
    return format_message(parsed, matches)


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        message = build_message(event)
        if message is None:
            # Nothing to say — fall through to the native dialog with no annotation.
            print("{}")
        else:
            print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    except Exception:
        # Fail open: never block or break the session. Exit 2 would DENY here.
        if os.environ.get("PERMISSION_LENS_DEBUG"):
            _log_debug(traceback.format_exc())
        print("{}")
    sys.exit(0)


def _log_debug(text):
    try:
        cache = Path(os.path.expanduser("~/.cache/permission-lens"))
        cache.mkdir(parents=True, exist_ok=True)
        with open(cache / "debug.log", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
