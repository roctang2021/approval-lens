"""The product as a function: an event in, a verdict out.

Reads no environment and does no host-specific I/O, so every adapter shares it
unchanged. How the event arrives, how the verdict is expressed, and whether a
human is present all belong to the adapter."""
import os
from collections import namedtuple

from .config import load_config
from .detail import extract_detail
from .parsing import Parsed
from .render import (SURFACE_HEADLESS, SURFACE_INTERACTIVE, passes_threshold,
                     render_reason)
from .rules import analyze, load_path_rules, load_web_rules, match_string_rules
from .heartbeat import record_heartbeat
from .tier2 import tier2_explanation

# ── per-tool analyzers ────────────────────────────────────────────────────────
#
# Each analyzer maps one tool's tool_input to a common Analysis:
#   Analysis(matches, tier2_subject, tier2_kind, detail_subject)
# or None to stay silent (unknown/empty input → native dialog, no annotation).
# tool_input field names verified from real transcripts (NOTES.md, item 1).
#
#   tier2_subject   what the model may see (path only, unless send_file_content)
#   detail_subject  what the offline detail extractor reads — never file bodies

Analysis = namedtuple("Analysis", "matches tier2_subject tier2_kind detail_subject")


def _analyze_bash(tool_input, config):
    command = tool_input.get("command")
    if not command or not command.strip():
        return None
    parsed = Parsed(command)
    return Analysis(analyze(parsed), command, "bash", command)


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
    # Tier 2 subject is the PATH only by default. File content is a much larger
    # data surface, so it is sent only when llm.send_file_content is on.
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



# ── assessment core ───────────────────────────────────────────────────────────
#
# `assess` is the whole product as a function: event in, verdict out. It reads
# no environment and performs no I/O beyond the rule/locale files and the
# optional Tier 2 call, so every host adapter can share it unchanged. Anything
# host-specific — how the event arrives, how the verdict is expressed, whether
# a human is present — belongs to the adapter below.

Assessment = namedtuple("Assessment", "matches asked reason tier2_outcome")
SILENT = Assessment(matches=(), asked=False, reason=None, tier2_outcome="off")


def assess(event, config, surface=SURFACE_INTERACTIVE):
    """Decide what, if anything, to say about one pending tool call.

    `config` must come from load_config()/validate_config(): every documented
    key is then guaranteed present, which is why this function indexes directly
    rather than defending against shapes that cannot occur.

    `reason is None` means stay out of the way entirely — no decision field, no
    forced prompt, allowlist and native dialog exactly as if the plugin were not
    installed.
    """
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

    # Tier 2 runs only for calls that will actually reach a dialog.
    tier2 = tier2_explanation(analysis.tier2_subject, config,
                              analysis.tier2_kind, event)
    # detail_subject is the small, clean subject (command / URL / path) — never
    # file contents, so the detail can't leak a file body onto the dialog.
    reason = render_reason(
        analysis.matches,
        lang=config["lang"],
        max_chars=config["max_message_chars"],
        llm_text=tier2.text,
        detail=extract_detail(analysis.matches[0], None, analysis.detail_subject),
    )
    return Assessment(analysis.matches, True, reason, tier2.outcome)


def build_message(event, config=None, surface=SURFACE_INTERACTIVE):
    """assess() plus the heartbeat: the reason string, or None to print {}.

    Kept as the convenience entry point for callers that only want the text.
    """
    config = config if config is not None else load_config()
    verdict = assess(event, config, surface)
    # Heartbeat last: it records "this call was checked" even when the answer is
    # {}, and it carries the Tier 2 outcome.
    record_heartbeat(event.get("tool_name"), verdict.matches, verdict.asked,
                     verdict.tier2_outcome)
    return verdict.reason
