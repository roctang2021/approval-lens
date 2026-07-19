#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Permission Lens — static analyzer + optional LLM explainer for Claude Code
permission dialogs.

Entry point for the `PermissionRequest` hook. Reads the pending permission
request from stdin, produces a plain-language explanation + risk assessment, and
prints it as `{"systemMessage": "..."}` on stdout. It NEVER returns a decision
field, so the native permission dialog always shows — augmenting the human's
judgment, not replacing it.

Two tiers:
  * Tier 1 (always on): offline rule engine over `rules.yaml`. Stdlib + PyYAML.
  * Tier 2 (opt-in via config, default OFF): one Anthropic Messages API call
    that adds a model-written one-liner. Hard wall-clock deadline; any failure
    silently degrades to the Tier 1 message. The request body contains ONLY a
    static system prompt and the command string — never cwd, session id, or
    transcript contents.

Config: `~/.config/permission-lens/config.json` (see DEFAULT_CONFIG below).
Unknown/invalid values fall back per-key to the defaults — a broken config can
never break the hook. Env overrides `PERMISSION_LENS_CONFIG` and
`PERMISSION_LENS_CACHE_DIR` exist for tests and debugging.

Correctness invariants (see NOTES.md for the doc sections these come from):
  * Exactly one JSON object is printed to stdout, on every code path.
  * The script exits 0 on every code path. On `PermissionRequest`, exit 2 would
    DENY the permission, so any failure fails OPEN: print `{}` and exit 0.
  * No `hookSpecificOutput` / `decision` is ever emitted.

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

RULES_PATH = Path(__file__).with_name("rules.yaml")

# ── configuration ─────────────────────────────────────────────────────────────

CONFIG_PATH_ENV = "PERMISSION_LENS_CONFIG"      # test/debug override for the config path
DEFAULT_CONFIG_PATH = "~/.config/permission-lens/config.json"
CACHE_DIR_ENV = "PERMISSION_LENS_CACHE_DIR"     # test/debug override for the cache dir
DEFAULT_CACHE_DIR = "~/.cache/permission-lens"

DEFAULT_CONFIG = {
    "lang": "en",                        # "en" | "zh"
    "min_severity_to_annotate": "info",  # "info" | "low" | "medium" | "high"
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
    },
}

_LANGS = ("en", "zh")
_SEVERITY_THRESHOLDS = ("info", "low", "medium", "high")
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
    if raw.get("lang") in _LANGS:
        cfg["lang"] = raw["lang"]
    if raw.get("min_severity_to_annotate") in _SEVERITY_THRESHOLDS:
        cfg["min_severity_to_annotate"] = raw["min_severity_to_annotate"]
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
    "en": {
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
    },
    "zh": {
        "ls": "列出目录内容",
        "cat": "输出文件内容",
        "cd": "切换工作目录",
        "cp": "复制文件",
        "mv": "移动或重命名文件",
        "mkdir": "创建目录",
        "touch": "创建文件或更新时间戳",
        "echo": "输出文本",
        "grep": "搜索文本",
        "rg": "搜索文本(ripgrep)",
        "find": "搜索文件系统",
        "sed": "编辑文本流",
        "awk": "处理文本",
        "python": "运行 Python 程序",
        "python3": "运行 Python 程序",
        "node": "运行 Node.js 程序",
        "make": "运行 make 目标",
        "brew": "运行 Homebrew 命令",
        "docker": "运行 Docker 命令",
        "kubectl": "运行 kubectl 命令",
    },
}
_FALLBACK_SUMMARY = {"en": "Runs a shell command", "zh": "运行一条 shell 命令"}
_RUNS_LABEL = {"en": "Runs", "zh": "运行"}
_SUBCOMMAND_TOOLS = {"git", "npm", "pnpm", "yarn", "docker", "kubectl", "cargo", "go", "pip", "pip3", "brew", "gh"}


def neutral_summary(parsed, lang=LANG):
    lang = lang if lang in _LANGS else "en"
    sc = parsed.simple_commands[0] if parsed.simple_commands else None
    if not sc or not sc.name:
        return _FALLBACK_SUMMARY[lang]
    name = sc.name
    _, args = sc.flags_and_args()
    if name in _SUBCOMMAND_TOOLS and args:
        return f"{_RUNS_LABEL[lang]}: {name} {args[0]}"
    if name in _VERB_PHRASES[lang]:
        return _VERB_PHRASES[lang][name]
    return f"{_RUNS_LABEL[lang]} `{name}`"


# ── message formatting ────────────────────────────────────────────────────────

LLM_EMOJI = "🤖"


def format_message(parsed, matches, lang=LANG, max_chars=MAX_MESSAGE_CHARS, llm_text=None):
    if not matches:
        lines = [f"{INFO_EMOJI} {neutral_summary(parsed, lang)}"]
    else:
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
    # Tier 2 line goes last so truncation always prefers the deterministic
    # Tier 1 content over the model-written extra.
    if llm_text:
        lines.append(f"{LLM_EMOJI} {llm_text}")
    return _truncate("\n".join(lines), max_chars)


def passes_threshold(matches, min_severity):
    """min_severity_to_annotate filter: 'info' annotates everything (incl. the
    neutral summary); higher values require a rule match at/above that level."""
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
# Dialogs show short commands; skip Tier 2 for pathological inputs.
LLM_MAX_COMMAND_CHARS = 4000

LLM_SYSTEM_PROMPT = {
    "en": (
        "You explain shell commands shown in a permission dialog. The user "
        "message is exactly one shell command. Reply with 1-2 short plain-text "
        "sentences in English: what the command does and any notable risk. "
        "No markdown, no preamble, no code blocks."
    ),
    "zh": (
        "你负责解释权限弹框里出现的 shell 命令。用户消息就是一条 shell 命令本身。"
        "用 1-2 句简短的中文纯文本回答:这条命令做什么、有什么值得注意的风险。"
        "不要用 Markdown,不要客套开场白,不要代码块。"
    ),
}


def tier2_explanation(command, config):
    """Return a one-line model-written explanation, or None (silent fallback)."""
    llm = config.get("llm")
    if not isinstance(llm, dict) or not llm.get("enabled"):
        return None  # gate is pre-try, so it must tolerate unvalidated configs
    try:
        if len(command) > LLM_MAX_COMMAND_CHARS:
            return None
        model, lang = llm["model"], config.get("lang", "en")
        ttl_days = llm["cache_ttl_days"]
        cache_path = _llm_cache_path(command, model, lang)
        cached = _cache_lookup(cache_path, ttl_days)
        if cached is not None:
            return _one_line(cached) or None
        credential = _resolve_credential(llm)
        if credential is None:
            return None
        timeout = llm["timeout_seconds"]
        text = _run_with_deadline(
            lambda: _post_messages_api(command, model, lang, credential, timeout),
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


def _post_messages_api(command, model, lang, credential, timeout):
    # Lazy import keeps Tier 1 startup lean (urllib.request pulls in a lot).
    import urllib.request

    # PRIVACY INVARIANT: the request body is a static system prompt plus the
    # command string, nothing else. No cwd, session_id, or transcript content.
    body = json.dumps({
        "model": model,
        "max_tokens": LLM_MAX_TOKENS,
        "system": LLM_SYSTEM_PROMPT.get(lang, LLM_SYSTEM_PROMPT["en"]),
        "messages": [{"role": "user", "content": command}],
    }).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "anthropic-version": LLM_API_VERSION,
    }
    kind, value = credential
    if kind == "api_key":
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


def _llm_cache_path(command, model, lang):
    digest = hashlib.sha256(f"{model}\n{lang}\n{command}".encode("utf-8")).hexdigest()
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


# ── M4 extension point (no-op in M1–M3) ───────────────────────────────────────

def notify(payload):
    """Stub for the future companion localhost panel (milestone M4).

    A later `notify_url` config key will POST the pending request here so a web
    page can render a richer breakdown. Intentionally does nothing today.
    """
    return None


# ── entry point ───────────────────────────────────────────────────────────────

def build_message(event, config=None):
    """Pure core: event dict -> systemMessage string (or None to stay silent)."""
    config = config if config is not None else load_config()
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
    if not passes_threshold(matches, config["min_severity_to_annotate"]):
        return None
    # Tier 2 runs only for commands we're actually going to annotate.
    llm_text = tier2_explanation(command, config)
    return format_message(
        parsed, matches,
        lang=config["lang"],
        max_chars=config["max_message_chars"],
        llm_text=llm_text,
    )


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        message = build_message(event, load_config())
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
        cache = _cache_dir()  # honors PERMISSION_LENS_CACHE_DIR like all writes
        cache.mkdir(parents=True, exist_ok=True)
        with open(cache / "debug.log", "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
