"""Permission Lens — the host-independent engine.

`assess(event, config, surface)` is the whole product as a function. Everything
here is portable Python; anything that knows about a specific coding agent
lives in that agent's adapter (see hooks/permission_lens.py for Claude Code).

Submodules are importable directly (`from lens import tier2`) for tests and
tools that need internals; the names below are the supported surface.
"""
from .config import (CONFIG_PATH_ENV, DEFAULT_CONFIG, DEFAULT_CONFIG_PATH, LANG,
                     MAX_MESSAGE_CHARS, load_config, validate_config)
from .core import (Analysis, Assessment, SURFACE_HEADLESS, SURFACE_INTERACTIVE,
                   TOOL_ANALYZERS, assess, build_message)
from .detail import extract_detail
from .heartbeat import HEARTBEAT_FILE, plugin_version, record_heartbeat
from .context import TASK_CONTEXT_MAX_CHARS, task_context
from .locales import (BASE_LANG, INFO_EMOJI, SEVERITY_EMOJI, SEVERITY_ORDER,
                      available_langs, load_locale, rule_text, severity_label,
                      ui_text)
from .paths import HOOKS_DIR, LOCALES_DIR
from .parsing import Parsed, SimpleCommand
from .predicates import has_flag
from .render import PART_SEP, passes_threshold, render_reason
from .rules import (analyze, load_path_rules, load_rules, load_web_rules,
                    match_string_rules)
from .tier2 import (LLM_API_URL, LLM_API_VERSION, LLM_MAX_COMMAND_CHARS,
                    LLM_OAUTH_BETA, LLM_PROMPT_KINDS, TIER2_OUTCOMES, Tier2Result,
                    is_safety_verdict, tier2_explanation)
from .util import CACHE_DIR_ENV, cache_dir, one_line

__all__ = [
    "assess", "build_message", "Assessment", "Analysis",
    "SURFACE_INTERACTIVE", "SURFACE_HEADLESS",
    "load_config", "validate_config", "DEFAULT_CONFIG", "LANG", "MAX_MESSAGE_CHARS",
    "CONFIG_PATH_ENV", "DEFAULT_CONFIG_PATH",
    "Parsed", "SimpleCommand", "analyze", "match_string_rules", "has_flag",
    "load_rules", "load_web_rules", "load_path_rules", "TOOL_ANALYZERS",
    "render_reason", "passes_threshold", "extract_detail", "PART_SEP",
    "load_locale", "available_langs", "rule_text", "ui_text", "severity_label",
    "SEVERITY_ORDER", "SEVERITY_EMOJI", "INFO_EMOJI", "BASE_LANG",
    "HOOKS_DIR", "LOCALES_DIR", "task_context", "TASK_CONTEXT_MAX_CHARS",
    "tier2_explanation", "Tier2Result", "TIER2_OUTCOMES", "is_safety_verdict",
    "LLM_API_URL", "LLM_API_VERSION", "LLM_OAUTH_BETA", "LLM_PROMPT_KINDS",
    "LLM_MAX_COMMAND_CHARS",
    "record_heartbeat", "plugin_version", "HEARTBEAT_FILE",
    "cache_dir", "one_line", "CACHE_DIR_ENV",
]
