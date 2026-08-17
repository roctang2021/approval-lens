#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Permission Lens — static analyzer + optional LLM explainer for Claude Code
permission dialogs.

The Claude Code adapter, and the plugin's hook entry point. The engine
itself lives in `lens/` and knows nothing about Claude Code.

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

Two tiers, both in `lens/`:
  * Tier 1 (always on): offline rule engine over `rules.yaml`. Stdlib + PyYAML.
  * Tier 2 (opt-in via config, default OFF): one Anthropic Messages API call
    that adds a model-written one-liner. Hard wall-clock deadline; any failure
    silently degrades to the Tier 1 reason.

Config: `~/.config/permission-lens/config.json` (see `lens/config.py`).
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
import json
import os
import sys
import traceback

from lens import SURFACE_HEADLESS, SURFACE_INTERACTIVE, build_message, load_config
from lens.util import log_debug

# ── Claude Code adapter ───────────────────────────────────────────────────────
#
# Everything below is specific to ONE host: the stdin event shape, the
# `hookSpecificOutput` response protocol, and how to tell whether a human is
# present. A second host means a second adapter, not a second core.

# Entrypoints where no human is present to answer a prompt. Matched EXACTLY and
# kept to surfaces actually observed, because the two mistakes are not equal:
# mistaking interactive for headless only costs the explanation (the native
# dialog still runs), while mistaking headless for interactive turns an
# allowlisted call into a failure. An unknown or absent value therefore keeps
# the asking behavior rather than silencing the plugin.
NON_INTERACTIVE_ENTRYPOINTS = frozenset({"sdk-cli", "sdk-py", "sdk-ts"})
ENTRYPOINT_ENV = "CLAUDE_CODE_ENTRYPOINT"


def claude_surface(environ=None):
    """Which surface this Claude Code process is: interactive or headless."""
    environ = os.environ if environ is None else environ
    value = environ.get(ENTRYPOINT_ENV, "").strip()
    return SURFACE_HEADLESS if value in NON_INTERACTIVE_ENTRYPOINTS else SURFACE_INTERACTIVE


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        reason = build_message(event, load_config(), claude_surface())
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
        log_debug("main: " + traceback.format_exc())
        print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
