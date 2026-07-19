#!/usr/bin/env python3
"""Probe: does PreToolUse permissionDecision="ask" render its reason on the dialog?

Docs (hooks § PreToolUse decision control) say permissionDecisionReason is
"shown to the user but not Claude" for "ask" — but not WHERE. This probe always
returns "ask" with an unmistakable two-line marker and logs every invocation
(stdin + stdout) to ~/.cache/permission-lens/probe-ask.log, so a live session
proves both that the hook fired and where the text landed.

Not part of the plugin — register it manually per README.md in this directory.
Stdlib only, so it runs under the bare `python3` even from Desktop's minimal
GUI PATH. Never gates: any internal error prints {} and exits 0 (on PreToolUse,
exit 2 would block the tool call — never do that here).
"""
import datetime
import json
import pathlib
import sys

MARKER = (
    "🔎 PROBE-ASK line 1: if you can read this ON the permission dialog, "
    "the reason renders there / 这行字出现在权限弹框上即证明 reason 上弹框\n"
    "🔎 PROBE-ASK line 2: second line, testing multi-line rendering / 第二行，测多行渲染"
)


def main():
    raw = sys.stdin.read()
    out_line = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": MARKER,
            }
        },
        ensure_ascii=False,
    )
    log = pathlib.Path.home() / ".cache" / "permission-lens" / "probe-ask.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(
            f"--- {datetime.datetime.now().isoformat()}\n"
            f"IN: {raw.strip()}\n"
            f"OUT: {out_line}\n"
        )
    print(out_line)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("{}")
    sys.exit(0)
