#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Claude Code PreToolUse adapter for Approval Lens.

Read one JSON event from stdin and emit ask + reason, or {}. Handled errors
exit zero. Known headless entrypoints default to silence because an ask can
fail a tool call when no user can answer. Matching lives in lens/.

This project studied dyad-sh/dyad .claude/hooks/ (Apache-2.0) for stdin
handling and shell patterns; no code was copied or adapted."""
import json
import os
import sys
import traceback

from lens import SURFACE_HEADLESS, SURFACE_INTERACTIVE, build_message, load_config
from lens.util import log_debug

# Claude-specific event transport and approval response.

# Recognize observed headless values exactly. Unknown values retain the
# interactive default; this environment variable is not a universal host API.
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
            # Request confirmation with a reason; the host controls how it is presented.
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": reason,
                }
            }, ensure_ascii=False))
    except Exception:
        # On handled errors, emit no decision. PreToolUse exit 2 would block the call.
        log_debug("main: " + traceback.format_exc())
        print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
