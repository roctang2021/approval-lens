"""Load and validate configuration.

Consumers expect all default keys; build configs through validate_config()."""
import json
import math
import os

import traceback
from .locales import available_langs
from .util import log_debug

MAX_MESSAGE_CHARS = 500  # default; overridable via config "max_message_chars"
LANG = "en"              # default; overridable via config "lang"


CONFIG_PATH_ENV = "APPROVAL_LENS_CONFIG"      # test/debug override for the config path
DEFAULT_CONFIG_PATH = "~/.config/approval-lens/config.json"

DEFAULT_CONFIG = {
    "lang": "en",                        # locale code
    # Request confirmation for rule matches at or above the threshold.
    "ask": {"min_severity": "high",      # "low" | "medium" | "high"
            # Default to silence when the adapter identifies a headless run.
            # An ask without a user to answer may fail the tool call.
            "non_interactive": "silent"},  # "silent" | "ask"
    "max_message_chars": MAX_MESSAGE_CHARS,
    "llm": {
        "enabled": False,                # Tier 2 is strictly opt-in
        "model": "claude-sonnet-5",
        # The model deadline adds to hook latency; leave time for startup and rules.
        "timeout_seconds": 5.0,          # hard wall-clock deadline for the API call
        # Resolve an API key from the environment, then the configured file.
        "api_key_env": "ANTHROPIC_API_KEY",
        # Optional key file for hosts that do not inherit shell environment variables.
        "api_key_file": "",
        "cache_ttl_days": 7,             # 0 disables the response cache
        # File content and user context require separate opt-ins.
        "send_file_content": False,
        "send_task_context": False,
    },
}

_ASK_THRESHOLDS = ("low", "medium", "high")  # only thresholds for matched risks
# Leave room for the JSON envelope within the hook output limit.
_MSG_CHARS_MIN, _MSG_CHARS_MAX = 80, 9000
# Leave startup time within the 10-second hook timeout.
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
        # Log malformed configuration when debug logging is enabled.
        log_debug("config %s unusable: %s" % (path, traceback.format_exc()))
    return validate_config(raw)


def validate_config(raw):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    # Accept installed locale codes; otherwise retain the default.
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
        for key in ("api_key_env", "api_key_file"):
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
