#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Permission Lens — static analyzer + optional LLM explainer for Claude Code
permission dialogs.

Entry point for the `PreToolUse` hook. Reads the pending tool call from stdin;
when Tier 1 finds a risk at/above the configured `ask.min_severity` (default:
high), it prints a `permissionDecision: "ask"` with a one-line plain-language
explanation as the `permissionDecisionReason` — which Claude Code renders ON
the permission dialog (verified 2026-07-19, see NOTES.md § PreToolUse probe).
For everything below the threshold it prints `{}` and stays invisible: the
allowlist, permission rules, and native dialog behave exactly as if the plugin
were not installed.

It NEVER returns "allow" or "deny". "ask" only guarantees the native dialog
appears (it "floors the decision at a prompt" — CHANGELOG 2.1.211); the human
always decides. That is the never-gatekeeper core: the plugin can add a prompt
for a risky call, but can never approve or block anything.

Two tiers:
  * Tier 1 (always on): offline rule engine over `rules.yaml`. Stdlib + PyYAML.
  * Tier 2 (opt-in via config, default OFF): one Anthropic Messages API call
    that adds a model-written one-liner. Hard wall-clock deadline; any failure
    silently degrades to the Tier 1 reason. The request body contains ONLY a
    static system prompt and the command string — never cwd, session id, or
    transcript contents.

Config: `~/.config/permission-lens/config.json` (see DEFAULT_CONFIG below).
Unknown/invalid values fall back per-key to the defaults — a broken config can
never break the hook. Env overrides `PERMISSION_LENS_CONFIG` and
`PERMISSION_LENS_CACHE_DIR` exist for tests and debugging.

Correctness invariants (see NOTES.md for the doc sections these come from):
  * Exactly one JSON object is printed to stdout, on every code path.
  * The script exits 0 on every code path. On `PreToolUse`, exit 2 would BLOCK
    the tool call, so any failure fails OPEN: print `{}` and exit 0.
  * `permissionDecision` is only ever "ask" — never "allow", never "deny".
  * The reason is a single line: the dialog collapses `\\n` (probe-verified),
    so multi-line text would render as run-together words.

This project studied dyad-sh/dyad `.claude/hooks/` (Apache-2.0) for stdin
handling and shell-metacharacter patterns; no code was copied or adapted.
"""
import hashlib
import json
import math
import os
import re
import shlex
import sys
import threading
import time
import traceback
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - exercised only when pyyaml is missing
    yaml = None

# Tier 1 budget target: analysis must stay well under 50ms. See tests/test_performance.py.
MAX_MESSAGE_CHARS = 500  # default; overridable via config "max_message_chars"
LANG = "en"              # default; overridable via config "lang"

RULES_PATH = Path(__file__).with_name("rules.yaml")           # Bash
WEB_RULES_PATH = Path(__file__).with_name("rules_web.yaml")   # WebFetch (URL)
PATH_RULES_PATH = Path(__file__).with_name("rules_path.yaml") # Write / Edit

# ── locales ───────────────────────────────────────────────────────────────────
#
# All user-visible text lives in locales/<lang>.yaml, keyed by rule id (plus
# ui/verbs/llm_prompts/status sections). `en` is the base: every other locale is
# merged over it per key, so a partial or blank translation degrades string by
# string instead of breaking. Adding a language = adding one file, no code.

LOCALES_DIR = Path(__file__).with_name("locales")
BASE_LANG = "en"
_LOCALE_CACHE = {}


def available_langs():
    """Language codes with a locale file, e.g. ('en', 'ja', 'zh').

    The base language is always included: even with the locales directory
    missing, `lang: "en"` must stay a valid config value (it renders the
    built-in defaults).
    """
    try:
        langs = {p.stem for p in LOCALES_DIR.glob("*.yaml")}
    except Exception:
        langs = set()
    langs.add(BASE_LANG)
    return tuple(sorted(langs))


def _read_locale(lang):
    if yaml is None:
        return {}
    try:
        with open(LOCALES_DIR / f"{lang}.yaml", "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}  # missing/broken locale -> base language only


def _merge_locale(base, over):
    merged = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_locale(merged[key], value)
        elif isinstance(value, str):
            if value.strip():  # blank translation -> keep the base string
                merged[key] = value
        elif value is not None:
            merged[key] = value
    return merged


def load_locale(lang):
    """The requested locale merged over the English base, cached per process."""
    if not isinstance(lang, str) or not lang:
        lang = BASE_LANG
    if lang not in _LOCALE_CACHE:
        base = _read_locale(BASE_LANG)
        _LOCALE_CACHE[lang] = base if lang == BASE_LANG else _merge_locale(
            base, _read_locale(lang))
    return _LOCALE_CACHE[lang]


def rule_text(locale, rule_id, field):
    """`explanation` or `risk` for a rule id ("" when absent in every locale)."""
    entry = (locale.get("rules") or {}).get(rule_id) or {}
    value = entry.get(field)
    return value.strip() if isinstance(value, str) else ""


def ui_text(locale, key, default="", section="ui"):
    value = (locale.get(section) or {}).get(key)
    return value if isinstance(value, str) and value.strip() else default

# ── configuration ─────────────────────────────────────────────────────────────

CONFIG_PATH_ENV = "PERMISSION_LENS_CONFIG"      # test/debug override for the config path
DEFAULT_CONFIG_PATH = "~/.config/permission-lens/config.json"
CACHE_DIR_ENV = "PERMISSION_LENS_CACHE_DIR"     # test/debug override for the cache dir
DEFAULT_CACHE_DIR = "~/.cache/permission-lens"

DEFAULT_CONFIG = {
    "lang": "en",                        # "en" | "zh"
    # The ask gate: a rule match at/above this severity returns
    # permissionDecision "ask" + the explanation as the reason; anything below
    # prints {} (fully invisible — allowlists and native behavior untouched).
    # "high" is the default because 🔴 commands are almost never allowlisted,
    # so forcing a prompt there costs ~nothing; set "medium" to put 🟡 (e.g.
    # force-push) on the dialog too, accepting prompts for calls your rules
    # would have auto-allowed. "info" is deliberately not accepted: it would
    # prompt on every single tool call.
    "ask": {"min_severity": "high"},     # "low" | "medium" | "high"
    "max_message_chars": MAX_MESSAGE_CHARS,
    "llm": {
        "enabled": False,                # Tier 2 is strictly opt-in
        "model": "claude-haiku-4-5",
        "timeout_seconds": 3.0,          # hard wall-clock deadline for the API call
        # Credential resolution order: api_key_env (x-api-key header), then
        # auth_token_env (OAuth bearer, e.g. from `ant auth print-credentials`).
        "api_key_env": "ANTHROPIC_API_KEY",
        "auth_token_env": "ANTHROPIC_AUTH_TOKEN",
        "cache_ttl_days": 7,             # 0 disables the response cache
        # Whether to send Write/Edit file CONTENT to the model. Off by default:
        # a command string / URL / path is a far smaller data surface than a
        # file body. Must be literal true to enable.
        "send_file_content": False,
        # Whether to send the developer's CURRENT REQUEST (the last prompt in
        # this session) alongside the operation, so the model can say whether
        # the operation fits what was actually asked for. Off by default: this
        # is the one setting that puts your own words on the wire. It can only
        # enrich the explanation — severity and the ask decision come from the
        # offline rules and are never influenced by it.
        "send_task_context": False,
    },
    # Desktop notification channel (opt-in). Independent of the ask gate: it
    # fires for any flagged call at/above its own min_severity — including
    # calls the permission rules auto-allow, where it's the only signal.
    "notify": {
        "enabled": False,
        "min_severity": "high",  # info | low | medium | high
    },
}

_SEVERITY_THRESHOLDS = ("info", "low", "medium", "high")
_ASK_THRESHOLDS = ("low", "medium", "high")  # no "info": would ask on everything
# max_message_chars bounds: floor keeps at least a headline visible; ceiling stays
# under the 10,000-char hook output cap (NOTES.md, "Confirmed facts" item 3).
_MSG_CHARS_MIN, _MSG_CHARS_MAX = 80, 9000
# timeout ceiling: the 10s hook timeout in hooks.json covers the WHOLE uv run
# (uv resolve + interpreter start + rules load), so cap the API deadline low
# enough to leave real headroom even on a cold uv cache.
_TIMEOUT_MIN, _TIMEOUT_MAX = 0.1, 6.0


def load_config():
    """Read + validate the user config; any problem falls back per-key to defaults."""
    path = os.environ.get(CONFIG_PATH_ENV) or os.path.expanduser(DEFAULT_CONFIG_PATH)
    raw = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            raw = loaded
    except Exception:
        pass  # missing/unreadable/malformed config -> pure defaults (fail open)
    return _validate_config(raw)


def _validate_config(raw):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    # Any language with a locale file is valid; a typo falls back to the default
    # rather than silently rendering English under a wrong-looking config.
    if raw.get("lang") in available_langs():
        cfg["lang"] = raw["lang"]
    ask_raw = raw.get("ask")
    if isinstance(ask_raw, dict) and ask_raw.get("min_severity") in _ASK_THRESHOLDS:
        cfg["ask"]["min_severity"] = ask_raw["min_severity"]
    cfg["max_message_chars"] = _clamped_number(
        raw.get("max_message_chars"), cfg["max_message_chars"],
        _MSG_CHARS_MIN, _MSG_CHARS_MAX, want_int=True)
    llm_raw = raw.get("llm")
    if isinstance(llm_raw, dict):
        llm = cfg["llm"]
        llm["enabled"] = llm_raw.get("enabled") is True
        if isinstance(llm_raw.get("model"), str) and llm_raw["model"].strip():
            llm["model"] = llm_raw["model"].strip()
        llm["timeout_seconds"] = _clamped_number(
            llm_raw.get("timeout_seconds"), llm["timeout_seconds"],
            _TIMEOUT_MIN, _TIMEOUT_MAX)
        if isinstance(llm_raw.get("api_key_env"), str) and llm_raw["api_key_env"].strip():
            llm["api_key_env"] = llm_raw["api_key_env"].strip()
        if isinstance(llm_raw.get("auth_token_env"), str) and llm_raw["auth_token_env"].strip():
            llm["auth_token_env"] = llm_raw["auth_token_env"].strip()
        llm["cache_ttl_days"] = _clamped_number(
            llm_raw.get("cache_ttl_days"), llm["cache_ttl_days"], 0, 365)
        llm["send_file_content"] = llm_raw.get("send_file_content") is True
        llm["send_task_context"] = llm_raw.get("send_task_context") is True
    notify_raw = raw.get("notify")
    if isinstance(notify_raw, dict):
        n = cfg["notify"]
        n["enabled"] = notify_raw.get("enabled") is True
        if notify_raw.get("min_severity") in _SEVERITY_THRESHOLDS:
            n["min_severity"] = notify_raw["min_severity"]
    return cfg


def _clamped_number(value, default, lo, hi, want_int=False):
    # bool is an int subclass; a bare true/false is never a valid number here.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    # Python's json accepts NaN/Infinity literals; NaN would clamp to the MAX
    # bound (nan comparisons are False), so treat non-finite as invalid.
    if not math.isfinite(value):
        return default
    value = max(lo, min(hi, value))
    return int(value) if want_int else float(value)

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
INFO_EMOJI = "ℹ️"


def severity_label(locale, severity):
    return ui_text(locale, f"severity_{severity}", severity.upper())


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


# ── detail extraction ─────────────────────────────────────────────────────────
#
# Rule copy describes a CATEGORY of risk ("downloads a script and runs it").
# The dialog is far more useful when it also names the concrete thing at hand
# ("from get.docker.com" vs "from a1b2c3.xyz"). Extractors pull that fact out
# of the command itself: offline, no model, no network, no privacy cost. A rule
# opts in via `detail: <name>` in rules*.yaml; anything that can't be resolved
# just yields nothing and the reason renders exactly as before.

_URL_IN_TEXT_RE = re.compile(r"[a-zA-Z][\w+.-]*://(?:[^/@?#\s]*@)?([^/:?#\s]+)")
# `of=` is the DESTINATION — the thing that gets overwritten. Naming the `if=`
# source instead would point at the harmless half of `dd if=/dev/zero of=/dev/disk2`.
_DD_TARGET_RE = re.compile(r"\bof=(\S+)")
_DEVICE_RE = re.compile(r"(/dev/[\w/]+)")
_DETAIL_MAX = 48


def _detail_url_host(parsed, subject):
    """Host of the first URL in the command — who the code/data comes from."""
    m = _URL_IN_TEXT_RE.search(subject or "")
    return m.group(1) if m else ""


def _detail_rm_target(parsed, subject):
    """What an rm -r would actually delete."""
    for sc in _rm_commands(parsed or Parsed(subject or "")):
        targets = _rm_targets(sc)
        if targets:
            return " ".join(targets[:2])
    return ""


def _detail_device(parsed, subject):
    """The device being written to/formatted — never the read source."""
    m = _DD_TARGET_RE.search(subject or "") or _DEVICE_RE.search(subject or "")
    return m.group(1) if m else ""


def _detail_path(parsed, subject):
    """The file being written/edited (kept as given, ~ not expanded)."""
    return (subject or "").strip()


DETAIL_EXTRACTORS = {
    "url_host": _detail_url_host,
    "rm_target": _detail_rm_target,
    "device": _detail_device,
    "path": _detail_path,
}


def extract_detail(rule, parsed, subject):
    """Short concrete fact for a matched rule, or "" when there's nothing to add."""
    fn = DETAIL_EXTRACTORS.get(rule.get("detail") or "")
    if not fn:
        return ""
    try:
        value = _one_line(str(fn(parsed, subject) or ""))
    except Exception:
        return ""
    if len(value) > _DETAIL_MAX:
        value = value[:_DETAIL_MAX - 1] + "…"
    return value


# ── rule engine ───────────────────────────────────────────────────────────────

_RULES_CACHE = {}  # keyed by yaml path -> compiled rule list


def _load_rules_from(path, default_field="path"):
    if path in _RULES_CACHE:
        return _RULES_CACHE[path]
    if yaml is None:
        _RULES_CACHE[path] = []
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    rules = []
    for raw in data.get("rules", []):
        rules.append({
            "id": raw["id"],
            "category": raw.get("category", ""),
            "severity": raw.get("severity", "low"),
            "regex": re.compile(raw["regex"]) if raw.get("regex") else None,
            "predicate": raw.get("predicate"),
            "scope": raw.get("scope", "whole"),
            # which subject string a string-rule matches against (see match_string_rules)
            "field": raw.get("field", default_field),
            # optional DETAIL_EXTRACTORS name: the concrete fact to name on the dialog
            "detail": raw.get("detail", ""),
        })  # user-visible text is resolved per language from locales/<lang>.yaml
    _RULES_CACHE[path] = rules
    return rules


def load_rules():
    return _load_rules_from(RULES_PATH)  # Bash rules (name kept for existing tests)


def load_web_rules():
    return _load_rules_from(WEB_RULES_PATH, default_field="url")


def load_path_rules():
    return _load_rules_from(PATH_RULES_PATH)  # default field "path"


def _sort_by_severity(matches):
    matches.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 0), reverse=True)
    return matches


def analyze(parsed, rules=None):
    """Bash analyzer: matched rules, highest severity first (dedup by rule id)."""
    rules = rules if rules is not None else load_rules()
    matches = [rule for rule in rules if _rule_matches(rule, parsed)]
    return _sort_by_severity(matches)


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


def match_string_rules(rules, subjects):
    """Match regex rules against a {field: string} map (WebFetch / Write / Edit).

    `subjects` maps a rule's `field` (e.g. "url", "path", "content") to the
    string that field's rules run against. A rule whose field is absent from
    the map is skipped.
    """
    matches = []
    for rule in rules:
        regex = rule["regex"]
        subject = subjects.get(rule["field"])
        if regex and subject and regex.search(subject):
            matches.append(rule)
    return _sort_by_severity(matches)


# ── neutral "what it does" summary ────────────────────────────────────────────

# Verb phrasing lives in the locale files (`verbs` section), so a no-risk-match
# notification still gets a line in the reader's language.
_SUBCOMMAND_TOOLS = {"git", "npm", "pnpm", "yarn", "docker", "kubectl", "cargo", "go", "pip", "pip3", "brew", "gh"}


def neutral_summary(parsed, lang=LANG):
    locale = load_locale(lang)
    runs = ui_text(locale, "runs", "Runs")
    sc = parsed.simple_commands[0] if parsed.simple_commands else None
    if not sc or not sc.name:
        return ui_text(locale, "fallback_summary", "Runs a shell command")
    name = sc.name
    _, args = sc.flags_and_args()
    if name in _SUBCOMMAND_TOOLS and args:
        return f"{runs}: {name} {args[0]}"
    verb = ui_text(locale, name, "", section="verbs")
    return verb or f"{runs} `{name}`"


# Grab the host from a URL without importing urllib (kept lazy for Tier 2);
# strip any userinfo so credentials are never echoed into the summary.
_URL_HOST_RE = re.compile(r"^[a-zA-Z][\w+.-]*://(?:[^/@?#\s]*@)?([^/:?#\s]+)")


def neutral_summary_web(url, lang=LANG):
    label = ui_text(load_locale(lang), "fetches", "Fetches")
    m = _URL_HOST_RE.search(url or "")
    host = m.group(1) if m else (url or "").strip()[:60]
    return f"{label} {host}" if host else label


def neutral_summary_path(file_path, label_key, lang=LANG):
    label = ui_text(load_locale(lang), label_key, label_key.capitalize())
    base = os.path.basename((file_path or "").rstrip("/")) or (file_path or "")
    return f"{label} {base}"


# ── reason formatting ─────────────────────────────────────────────────────────
#
# The reason renders on the permission dialog as ONE flowing line (the dialog
# collapses \n — probe-verified 2026-07-19). Each part starts with an emoji, so
# emojis double as visual separators: 🔴 headline · 🟡 extra risk · 🤖 model line.

LLM_EMOJI = "🤖"
DETAIL_EMOJI = "📍"  # marks the concrete target; no localized label needed


def render_reason(matches, lang=LANG, max_chars=MAX_MESSAGE_CHARS, llm_text=None,
                  detail=""):
    """Matched rules -> the single-line permissionDecisionReason.

    Requires at least one match (the ask gate guarantees it). The headline is
    the top rule's `risk` sentence — written in the locale as a self-contained
    plain-language sentence: what the call does AND why it matters, no jargon.
    `detail` is the concrete target pulled from the command itself (see
    extract_detail); it needs no translation, so it rides on the 📍 marker
    rather than a localized label.
    """
    locale = load_locale(lang)
    top = matches[0]
    sev = top["severity"]
    emoji = SEVERITY_EMOJI.get(sev, INFO_EMOJI)
    parts = [f"{emoji} {severity_label(locale, sev)} · {rule_text(locale, top['id'], 'risk')}"]
    if detail:
        parts.append(f"{DETAIL_EMOJI} {detail}")
    # Up to two additional distinct risks (dedupe by category to avoid near-dupes);
    # extras use the short `explanation` phrase, not the full sentence.
    seen = {top["category"]}
    extras = 0
    for rule in matches[1:]:
        if rule["category"] in seen:
            continue
        seen.add(rule["category"])
        e = SEVERITY_EMOJI.get(rule["severity"], INFO_EMOJI)
        parts.append(f"{e} {rule_text(locale, rule['id'], 'explanation')}")
        extras += 1
        if extras == 2:
            break
    # Tier 2 goes last so truncation always prefers the deterministic Tier 1
    # content over the model-written extra.
    if llm_text:
        parts.append(f"{LLM_EMOJI} {llm_text}")
    return _truncate(" ".join(_one_line(p) for p in parts), max_chars)


def passes_threshold(matches, min_severity):
    """Severity gate shared by ask.min_severity and notify.min_severity:
    'info' passes everything (incl. no-match calls); higher values require a
    rule match at/above that level. ask never accepts 'info', so the ask gate
    can only fire on an actual match."""
    threshold = SEVERITY_ORDER.get(min_severity, 0)  # "info" and unknown -> 0
    if not matches:
        return threshold <= 0
    return SEVERITY_ORDER.get(matches[0]["severity"], 0) >= threshold


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + "…"


# ── Tier 2: optional LLM explainer (default OFF) ──────────────────────────────
#
# One Anthropic Messages API call per (model, lang, command), cached on disk.
# Every failure path — disabled, no key, network error, non-2xx, timeout,
# unparseable response — returns None and the caller degrades to Tier 1 alone.
# Raw HTTP via urllib (stdlib) by design: no SDK dependency in a hook script.

# Endpoint + headers per the Messages API reference (verified 2026-07-19):
# POST https://api.anthropic.com/v1/messages with x-api-key + anthropic-version.
LLM_API_URL = "https://api.anthropic.com/v1/messages"
LLM_API_VERSION = "2023-06-01"
# OAuth bearer tokens (e.g. from `ant auth login`) go on `Authorization: Bearer`
# and require this beta header on /v1/messages — an API key uses x-api-key.
LLM_OAUTH_BETA = "oauth-2025-04-20"
LLM_MAX_TOKENS = 300
# Dialogs show short subjects; skip Tier 2 for pathological inputs.
LLM_MAX_COMMAND_CHARS = 4000

# One system prompt per tool "kind", read from the locale's `llm_prompts`
# section so the model answers in the reader's language; the user message is
# the subject string (command / URL / file path [+ optional contents]) alone.
LLM_PROMPT_KINDS = ("bash", "url", "path")


def tier2_explanation(subject, config, kind="bash", event=None):
    """Return a one-line model-written explanation, or None (silent fallback).

    `subject` is the exact string sent to the model (command / URL / path[+content]);
    `kind` selects the system prompt. The developer's current request is added
    ONLY when llm.send_task_context is on; nothing else from the session (cwd,
    ids, transcript) is ever sent. Whatever comes back can only be appended to
    the explanation — it never affects severity or whether the dialog appears.
    """
    llm = config.get("llm")
    if not isinstance(llm, dict) or not llm.get("enabled"):
        return None  # gate is pre-try, so it must tolerate unvalidated configs
    try:
        if not subject or len(subject) > LLM_MAX_COMMAND_CHARS:
            return None
        if kind not in LLM_PROMPT_KINDS:
            kind = "bash"
        model, lang = llm["model"], config.get("lang", "en")
        task = task_context(event) if (event and llm.get("send_task_context")) else ""
        ttl_days = llm["cache_ttl_days"]
        # The task is part of the cache key: the same command under a different
        # request deserves a different answer.
        cache_path = _llm_cache_path(subject, model, lang, kind, task)
        cached = _cache_lookup(cache_path, ttl_days)
        if cached is not None:
            return _one_line(cached) or None
        credential = _resolve_credential(llm)
        if credential is None:
            return None
        timeout = llm["timeout_seconds"]
        text = _run_with_deadline(
            lambda: _post_messages_api(subject, model, lang, kind, credential,
                                       timeout, task),
            timeout,
        )
        text = _one_line(text or "")
        if not text:
            return None
        if ttl_days > 0:  # ttl 0 disables the cache entirely — reads AND writes
            _cache_store(cache_path, text)
        return text
    except Exception:
        if os.environ.get("PERMISSION_LENS_DEBUG"):
            _log_debug("tier2: " + traceback.format_exc())
        return None


def _one_line(text):
    """Collapse whitespace/newlines so the dialog gets a single tidy line."""
    return " ".join(text.split())


def _resolve_credential(llm):
    """User's own credentials only, from env: API key first, OAuth token second.

    Returns ("api_key", value) or ("oauth", value), or None when neither env
    var is set — subscription-only users without either simply get Tier 1.
    """
    api_key = os.environ.get(llm.get("api_key_env") or "", "").strip()
    if api_key:
        return ("api_key", api_key)
    token = os.environ.get(llm.get("auth_token_env") or "", "").strip()
    if token:
        return ("oauth", token)
    return None


def _post_messages_api(subject, model, lang, kind, credential, timeout, task=""):
    # Lazy import keeps Tier 1 startup lean (urllib.request pulls in a lot).
    import urllib.request

    system = ui_text(load_locale(lang), kind, "", section="llm_prompts") or ui_text(
        load_locale(BASE_LANG), "bash", "", section="llm_prompts")
    # PRIVACY INVARIANT: the request body is a static system prompt plus the
    # subject string — and, ONLY when llm.send_task_context is on, the
    # developer's current request. Never cwd, session id, or transcript beyond
    # that one line.
    if task:
        system += " " + (ui_text(load_locale(lang), "task_suffix", "", section="llm_prompts")
                         or ui_text(load_locale(BASE_LANG), "task_suffix", "",
                                    section="llm_prompts"))
        content = (f"<user_request>\n{task}\n</user_request>\n"
                   f"<operation>\n{subject}\n</operation>")
    else:
        content = subject
    body = json.dumps({
        "model": model,
        "max_tokens": LLM_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "anthropic-version": LLM_API_VERSION,
    }
    cred_kind, value = credential
    if cred_kind == "api_key":
        headers["x-api-key"] = value
    else:  # OAuth bearer token — different header AND a required beta flag
        headers["authorization"] = f"Bearer {value}"
        headers["anthropic-beta"] = LLM_OAUTH_BETA
    req = urllib.request.Request(LLM_API_URL, data=body, headers=headers, method="POST")
    # Socket-level timeout; the wall-clock cap is enforced by _run_with_deadline.
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for block in data.get("content", []):
        if block.get("type") == "text" and str(block.get("text", "")).strip():
            return str(block["text"]).strip()
    return None


def _run_with_deadline(fn, seconds):
    """Run fn in a worker thread with a hard wall-clock cap.

    urllib's timeout is per socket operation, so a slow-trickle response could
    exceed it in total. The daemon worker gives a true deadline: on expiry we
    abandon the thread (the socket timeout reaps it) and fall back to Tier 1.
    """
    box = {}

    def worker():
        try:
            box["value"] = fn()
        except Exception:
            if os.environ.get("PERMISSION_LENS_DEBUG"):
                _log_debug("tier2 fetch: " + traceback.format_exc())

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(seconds)
    return box.get("value")


def _cache_dir():
    return Path(os.path.expanduser(os.environ.get(CACHE_DIR_ENV) or DEFAULT_CACHE_DIR))


def _llm_cache_path(subject, model, lang, kind="bash", task=""):
    digest = hashlib.sha256(
        f"{model}\n{lang}\n{kind}\n{task}\n{subject}".encode("utf-8")).hexdigest()
    return _cache_dir() / "llm" / f"{digest}.json"


def _cache_lookup(path, ttl_days):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            entry = json.load(fh)
        text, created = entry.get("text"), entry.get("created")
        if not isinstance(text, str) or isinstance(created, bool) \
                or not isinstance(created, (int, float)):
            return None
        if time.time() - created > ttl_days * 86400:
            return None
        return text
    except Exception:
        return None  # missing or corrupt cache entry -> treat as a miss


def _cache_store(path, text):
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"text": text, "created": time.time()}, fh, ensure_ascii=False)
        os.replace(tmp, path)  # atomic on POSIX; concurrent hooks can't corrupt
    except Exception:
        # cache is best-effort only; don't leave a half-written tmp behind
        if tmp is not None:
            try:
                os.unlink(tmp)
            except Exception:
                pass


# ── desktop notification channel ──────────────────────────────────────────────
#
# Opt-in second channel alongside the on-dialog reason. On PreToolUse it fires
# BEFORE permission evaluation, so it also covers flagged calls the rules
# auto-allow (no dialog ever appears for those — the notification is the only
# signal). This is a best-effort SIDE EFFECT: it never touches stdout and any
# failure is swallowed, so fail-open / exit-0 / single-JSON are all preserved.


# Session label for notifications: which window is this? Titles live in the
# transcript as appended `custom-title` (user-set, authoritative) / `ai-title`
# (auto) lines — verified 2026-07-19 against a real transcript. Only read on
# the notification path (rare, and already paying for an osascript subprocess).
_TITLE_KEYS = (("custom-title", "customTitle"), ("ai-title", "aiTitle"))
_TRANSCRIPT_TAIL_BYTES = 4 * 1024 * 1024  # cap the scan on very long sessions
# The transcript also records the developer's current request as its own line
# (verified 2026-07-19). Used ONLY when llm.send_task_context is on.
_TASK_KEY = ("last-prompt", "lastPrompt")
TASK_CONTEXT_MAX_CHARS = 400


def _scan_transcript(path, wanted):
    """Latest value of each wanted (line type -> field) pair. Best effort."""
    found = {}
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if size > _TRANSCRIPT_TAIL_BYTES:
                fh.seek(size - _TRANSCRIPT_TAIL_BYTES)
                fh.readline()  # discard the partial line
            for line in fh:
                # Cheap pre-filter: these lines are a tiny fraction of a transcript.
                if not any(f'"{kind}"' in line for kind, _ in wanted):
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                for kind, key in wanted:
                    if entry.get("type") == kind and isinstance(entry.get(key), str):
                        found[kind] = entry[key].strip()
    except Exception:
        pass
    return found


def task_context(event, max_chars=TASK_CONTEXT_MAX_CHARS):
    """The developer's current request, or "" — gated by llm.send_task_context.

    This is the only place the plugin reads what the human actually typed, and
    it leaves the machine only when that setting is explicitly on.
    """
    path = (event or {}).get("transcript_path")
    if not isinstance(path, str) or not path:
        return ""
    text = _scan_transcript(path, (_TASK_KEY,)).get(_TASK_KEY[0], "")
    text = _one_line(text)
    return text[:max_chars - 1] + "…" if len(text) > max_chars else text


def session_label(event):
    """Short human name for the session: its title, else the project folder."""
    try:
        found = {}
        path = event.get("transcript_path")
        if isinstance(path, str) and path:
            # _scan_transcript swallows its own errors, so an unreadable
            # transcript still falls through to the folder-name fallback.
            found = _scan_transcript(path, _TITLE_KEYS)
        # A user-set title wins over the generated one, whichever came last.
        for kind, _ in _TITLE_KEYS:
            if found.get(kind):
                return _one_line(found[kind])[:60]
        cwd = event.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            return os.path.basename(cwd.rstrip("/")) or None
    except Exception:
        if os.environ.get("PERMISSION_LENS_DEBUG"):
            _log_debug("session_label: " + traceback.format_exc())
    return None


def maybe_notify(tool, matches, neutral, config, lang, event=None):
    try:
        n = config.get("notify")
        if not isinstance(n, dict) or not n.get("enabled"):
            return
        # "info" notifies on everything (incl. no-match neutral calls); higher
        # values require a rule match at/above that level. passes_threshold
        # handles the no-match case (threshold <= 0).
        if not passes_threshold(matches, n.get("min_severity", "high")):
            return
        # Resolved only past the gates — reading the transcript isn't free.
        session = session_label(event) if event else None
        # The session name goes in the TITLE, the most-scanned line: with
        # several windows running, "which one is asking me?" is the first
        # question a notification has to answer (the M6 pairing weakness).
        if matches:
            locale = load_locale(lang)
            top = matches[0]
            emoji = SEVERITY_EMOJI.get(top["severity"], INFO_EMOJI)
            head = f"{emoji} {severity_label(locale, top['severity'])}"
            detail = rule_text(locale, top["id"], "explanation")
        else:  # only reached at min_severity "info" — benign/neutral call
            head, detail = INFO_EMOJI, neutral
        send_desktop_notification(
            f"{head} · {session}" if session else head,
            f"{tool} · {detail}",
        )
    except Exception:
        if os.environ.get("PERMISSION_LENS_DEBUG"):
            _log_debug("notify: " + traceback.format_exc())


def send_desktop_notification(title, body):
    """Fire a macOS notification (no-op off darwin). Best-effort, short timeout."""
    if sys.platform != "darwin":
        return
    import subprocess  # lazy: keep Tier 1 startup lean
    script = 'display notification "%s" with title "%s"' % (
        _osa_escape(body), _osa_escape(title))
    subprocess.run(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3,
    )


def _osa_escape(text):
    # AppleScript string literal escaping; also flatten newlines to one line.
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


# ── heartbeat ─────────────────────────────────────────────────────────────────
#
# Answers "is the plugin alive, and was that call actually checked?" without
# touching the dialog: a clean dialog is otherwise indistinguishable from a
# dead hook. Every analyzed invocation updates one small local state file —
# timestamps, tool name, top severity, ask outcome; NEVER commands, URLs, or
# paths. Best-effort SIDE EFFECT like the notifier: failures are swallowed,
# stdout and exit codes untouched. Read it with scripts/lens-status.py.

HEARTBEAT_FILE = "heartbeat.json"
_COUNT_KEYS = ("total", "high", "medium", "low", "none", "asked")


def record_heartbeat(tool, matches, asked):
    try:
        path = _cache_dir() / HEARTBEAT_FILE
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        state = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                state = loaded
        except Exception:
            pass  # missing/corrupt heartbeat -> start fresh
        counts = state.get("counts") if state.get("today") == today else None
        if not isinstance(counts, dict):
            counts = {}
        counts = {k: _nonneg_int(counts.get(k)) for k in _COUNT_KEYS}
        severity = matches[0]["severity"] if matches else None
        bucket = severity if severity in ("high", "medium", "low") else "none"
        counts["total"] += 1
        counts[bucket] += 1
        if asked:
            counts["asked"] += 1
        fresh = {
            "version": 1,
            "updated": now,
            "today": today,
            "counts": counts,
            "last": {"ts": now, "tool": tool, "severity": severity, "asked": bool(asked)},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(fresh, fh, ensure_ascii=False)
        os.replace(tmp, path)  # atomic; a concurrent hook loses a count, never the file
    except Exception:
        if os.environ.get("PERMISSION_LENS_DEBUG"):
            _log_debug("heartbeat: " + traceback.format_exc())


def _nonneg_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


# ── M4 extension point (localhost panel — no-op today) ────────────────────────

def notify(payload):
    """Stub for the future companion localhost panel (milestone M4).

    A later `notify_url` config key will POST the pending request here so a web
    page can render a richer breakdown. Intentionally does nothing today.
    """
    return None


# ── per-tool analyzers ────────────────────────────────────────────────────────
#
# Each analyzer maps one tool's tool_input to a common Analysis:
#   (matches, neutral_summary, tier2_subject, tier2_kind, notify_subject)
# or None to stay silent (unknown/empty input → native dialog, no annotation).
# tool_input field names verified from real transcripts (NOTES.md, item 1).


def _analyze_bash(tool_input, config, lang):
    command = tool_input.get("command")
    if not command or not command.strip():
        return None
    parsed = Parsed(command)
    matches = analyze(parsed)
    return matches, neutral_summary(parsed, lang), command, "bash", command


def _analyze_webfetch(tool_input, config, lang):
    url = tool_input.get("url")  # WebFetch: {url, prompt}
    if not url or not str(url).strip():
        return None
    url = str(url).strip()
    matches = match_string_rules(load_web_rules(), {"url": url})
    # Send only the URL to Tier 2 — never the prompt (it may carry user data).
    return matches, neutral_summary_web(url, lang), url, "url", url


def _analyze_write(tool_input, config, lang):
    return _analyze_file(tool_input, config, lang,
                         content_key="content", label_key="writes")


def _analyze_edit(tool_input, config, lang):
    return _analyze_file(tool_input, config, lang,
                         content_key="new_string", label_key="edits")


def _analyze_file(tool_input, config, lang, content_key, label_key):
    # Write: {file_path, content}; Edit: {file_path, old_string, new_string}.
    path = tool_input.get("file_path")
    if not path or not str(path).strip():
        return None
    path = str(path)
    content = tool_input.get(content_key)
    content = str(content) if isinstance(content, str) else ""
    subjects = {"path": os.path.expanduser(path)}
    if content:
        subjects["content"] = content
    matches = match_string_rules(load_path_rules(), subjects)
    # Tier 2 subject is the PATH only by default. File content is a much larger
    # data surface, so it is sent only when llm.send_file_content is on.
    subject = path
    if (config.get("llm") or {}).get("send_file_content") and content:
        subject = f"{path}\n\n{content}"
    return matches, neutral_summary_path(path, label_key, lang), subject, "path", path


TOOL_ANALYZERS = {
    "Bash": _analyze_bash,
    "WebFetch": _analyze_webfetch,
    "Write": _analyze_write,
    "Edit": _analyze_edit,
}


# ── entry point ───────────────────────────────────────────────────────────────

def build_message(event, config=None):
    """Pure core: event dict -> the one-line ask reason, or None to print {}.

    None means the plugin stays out of the way entirely: no decision field, no
    forced prompt — allowlists and the native dialog behave as if it weren't
    installed. A string means "ask" with that string as the on-dialog reason.
    """
    config = config if config is not None else load_config()
    tool_name = event.get("tool_name")
    analyzer = TOOL_ANALYZERS.get(tool_name)
    if analyzer is None:  # uncovered tool -> never interfere
        return None
    result = analyzer(event.get("tool_input") or {}, config, config["lang"])
    if result is None:
        return None
    matches, neutral, subject, kind, notify_subject = result
    notify({"subject": notify_subject, "matches": [m["id"] for m in matches]})
    # Notification channel is independent of the ask gate (its own threshold),
    # so it runs first — it can flag calls that will auto-run without a dialog.
    maybe_notify(tool_name, matches, neutral, config, config["lang"], event)
    asked = passes_threshold(matches, config["ask"]["min_severity"])
    # Heartbeat: prove "this call was checked" even when the answer is {}.
    record_heartbeat(tool_name, matches, asked)
    if not asked:
        return None
    # Tier 2 runs only for calls we're actually going to put on a dialog.
    llm_text = tier2_explanation(subject, config, kind, event)
    # notify_subject is the small, clean subject (command / URL / path) — never
    # file contents, so the detail can't leak a file body onto the dialog.
    return render_reason(
        matches,
        lang=config["lang"],
        max_chars=config["max_message_chars"],
        llm_text=llm_text,
        detail=extract_detail(matches[0], None, notify_subject),
    )


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        reason = build_message(event, load_config())
        if reason is None:
            # Nothing to say — native permission behavior, untouched.
            print("{}")
        else:
            # "ask" floors the decision at a prompt and puts the reason on the
            # dialog. NEVER "allow"/"deny" — the human always decides.
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            }, ensure_ascii=False))
    except Exception:
        # Fail open: never block or break the session. Exit 2 would BLOCK here.
        if os.environ.get("PERMISSION_LENS_DEBUG"):
            _log_debug(traceback.format_exc())
        print("{}")
    sys.exit(0)


def _log_debug(text):
    try:
        cache = _cache_dir()  # honors PERMISSION_LENS_CACHE_DIR like all writes
        cache.mkdir(parents=True, exist_ok=True)
        with open(cache / "debug.log", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
