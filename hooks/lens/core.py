"""Assess pending actions and build localized explanations.

Inputs still use Claude tool fields; see docs/architecture.md for adapter boundaries."""
import os
from collections import namedtuple

from .config import load_config
from .detail import extract_detail
from .heartbeat import record_heartbeat
from .parsing import Parsed
from .render import passes_threshold, render_reason
from .rules import (analyze_command, load_path_rules, load_web_rules,
                    match_string_rules)
from .tier2 import tier2_explanation

# The adapter supplies interactivity; each host detects it differently.
SURFACE_INTERACTIVE = "interactive"
SURFACE_HEADLESS = "headless"


# Analyzers map Claude tool_input fields to shared matching/rendering inputs.
# The model subject may include opted-in content; detail_subject never does.

Analysis = namedtuple("Analysis", "matches tier2_subject tier2_kind detail_subject")


def _analyze_bash(tool_input, config):
    command = tool_input.get("command")
    if not command or not command.strip():
        return None
    parsed = Parsed(command)
    return Analysis(analyze_command(parsed), command, "bash", command)


def _analyze_webfetch(tool_input, config):
    url = tool_input.get("url")  # WebFetch: {url, prompt}
    if not url or not str(url).strip():
        return None
    url = str(url).strip()
    # Send only the URL to Tier 2 — never the prompt (it may carry user data).
    return Analysis(match_string_rules(load_web_rules(), {"url": url}), url, "url", url)


def _analyze_write(tool_input, config):
    return _analyze_file(tool_input, config, content_key="content")


def _analyze_edit(tool_input, config):
    return _analyze_file(tool_input, config, content_key="new_string")


def _analyze_file(tool_input, config, content_key):
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
    # Include file content in the model subject only with explicit opt-in.
    subject = path
    if config["llm"]["send_file_content"] and content:
        subject = f"{path}\n\n{content}"
    return Analysis(match_string_rules(load_path_rules(), subjects), subject, "path", path)


TOOL_ANALYZERS = {
    "Bash": _analyze_bash,
    "WebFetch": _analyze_webfetch,
    "Write": _analyze_write,
    "Edit": _analyze_edit,
}


Assessment = namedtuple("Assessment", "matches asked reason tier2_outcome")
SILENT = Assessment(matches=(), asked=False, reason=None, tier2_outcome="off")


def assess(event, config, surface=SURFACE_INTERACTIVE):
    """Assess a Claude-shaped event using a validated config.

    Returns reason=None when no extra confirmation is requested. May read rule,
    locale, cache and credential files, and call the optional model service."""
    analyzer = TOOL_ANALYZERS.get(event.get("tool_name"))
    if analyzer is None:  # uncovered tool -> never interfere
        return SILENT
    analysis = analyzer(event.get("tool_input") or {}, config)
    if analysis is None:  # unknown or empty input -> nothing to say
        return SILENT

    asked = passes_threshold(analysis.matches, config["ask"]["min_severity"])
    if asked and surface == SURFACE_HEADLESS and config["ask"]["non_interactive"] == "silent":
        # Nobody can answer, so "ask" fails the call instead of prompting.
        asked = False
    if not asked:
        return Assessment(analysis.matches, False, None, "off")

    # Only request a model note when the assessment requests confirmation.
    tier2 = tier2_explanation(analysis.tier2_subject, config,
                              analysis.tier2_kind, event)
    # Target extraction receives a command, URL or path, without file contents.
    reason = render_reason(
        analysis.matches,
        lang=config["lang"],
        max_chars=config["max_message_chars"],
        llm_text=tier2.text,
        detail=extract_detail(analysis.matches[0], None, analysis.detail_subject),
    )
    return Assessment(analysis.matches, True, reason, tier2.outcome)


def build_message(event, config=None, surface=SURFACE_INTERACTIVE):
    """Assess the event, record local status, and return a reason or None."""
    config = config if config is not None else load_config()
    verdict = assess(event, config, surface)
    # Record the check and model outcome even when there is no reason to display.
    record_heartbeat(event.get("tool_name"), verdict.matches, verdict.asked,
                     verdict.tier2_outcome)
    return verdict.reason
