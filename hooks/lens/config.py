"""Reading and validating the user's config.

validate_config is the ONLY sanctioned way to build a config. Everything
downstream indexes directly into the result, so hand-assembled dicts are not a
supported input — that ambiguity is what let a test drop a key the module
required."""
import json
import math
import os

import traceback
from .locales import available_langs
from .util import log_debug

MAX_MESSAGE_CHARS = 500  # default; overridable via config "max_message_chars"
LANG = "en"              # default; overridable via config "lang"

# ── configuration ─────────────────────────────────────────────────────────────

CONFIG_PATH_ENV = "PERMISSION_LENS_CONFIG"      # test/debug override for the config path
DEFAULT_CONFIG_PATH = "~/.config/permission-lens/config.json"

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
    "ask": {"min_severity": "high",      # "low" | "medium" | "high"
            # A headless run (`claude -p`, SDK, CI) has NOBODY to answer a
            # prompt, so "ask" there does not float the decision up to a human —
            # it fails the call outright. Measured 2026-08-14: an explicitly
            # allowlisted `sudo` under `claude -p` came back "blocked by a
            # permission hook ... it didn't execute". That makes the plugin a
            # gatekeeper, which is the one thing it must never be, so on a
            # known non-interactive surface it stays silent instead. Set
            # "ask" to keep the old behavior and accept the blocking.
            "non_interactive": "silent"},  # "silent" | "ask"
    "max_message_chars": MAX_MESSAGE_CHARS,
    "llm": {
        "enabled": False,                # Tier 2 is strictly opt-in
        # Measured 2026-08-14 on `sudo -n rm ...`: haiku-4-5 got the flag wrong
        # twice out of two ("runs without needing a password"), sonnet-5 right
        # twice out of two ("fails outright if there is no passwordless rule").
        # Three rounds of prompt tightening did not move haiku, so this is a
        # capability limit, not a wording problem. A confidently wrong sentence
        # spends the trust the verified half of the line is there to earn.
        "model": "claude-sonnet-5",
        # This deadline IS the dialog's latency — the hook runs before the
        # prompt appears. Measured medians: haiku 1.2s, sonnet 2.5s, sonnet
        # slowest 3.5s. At the old 3.0s sonnet would have missed the deadline
        # routinely, paying for a call whose answer never rendered.
        "timeout_seconds": 5.0,          # hard wall-clock deadline for the API call
        # Credential resolution order: api_key_env (x-api-key header), then
        # auth_token_env (OAuth bearer, e.g. from `ant auth print-credentials`),
        # then the *_file paths below.
        "api_key_env": "ANTHROPIC_API_KEY",
        "auth_token_env": "ANTHROPIC_AUTH_TOKEN",
        # Files holding the credential, one line, e.g. "~/.config/permission-lens/api-key".
        # GUI-launched apps (Claude Desktop) inherit neither shell exports nor,
        # in practice, `launchctl setenv` — verified 2026-07-24 on this machine,
        # where the app process had no ANTHROPIC_* vars even after a restart.
        # A file is the reliable channel there. Keep it chmod 600.
        "api_key_file": "",
        "auth_token_file": "",
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
}

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
    except FileNotFoundError:
        pass  # no config file is the normal case, not a failure
    except Exception:
        # A typo in the user's JSON silently reverted every setting they wrote.
        log_debug("config %s unusable: %s" % (path, traceback.format_exc()))
    return validate_config(raw)


def validate_config(raw):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    # Any language with a locale file is valid; a typo falls back to the default
    # rather than silently rendering English under a wrong-looking config.
    if raw.get("lang") in available_langs():
        cfg["lang"] = raw["lang"]
    ask_raw = raw.get("ask")
    if isinstance(ask_raw, dict) and ask_raw.get("min_severity") in _ASK_THRESHOLDS:
        cfg["ask"]["min_severity"] = ask_raw["min_severity"]
    if isinstance(ask_raw, dict) and ask_raw.get("non_interactive") in ("silent", "ask"):
        cfg["ask"]["non_interactive"] = ask_raw["non_interactive"]
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
        for key in ("api_key_env", "auth_token_env", "api_key_file", "auth_token_file"):
            value = llm_raw.get(key)
            if isinstance(value, str) and value.strip():
                llm[key] = value.strip()
        llm["cache_ttl_days"] = _clamped_number(
            llm_raw.get("cache_ttl_days"), llm["cache_ttl_days"], 0, 365)
        llm["send_file_content"] = llm_raw.get("send_file_content") is True
        llm["send_task_context"] = llm_raw.get("send_task_context") is True
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
