#!/usr/bin/env python3
"""Standalone Claude PreToolUse rendering probe; not installed with the plugin.

Always requests confirmation with a two-line marker. Logs complete input and
output to ~/.cache/approval-lens/probe-ask.log; use only safe test inputs.
Handled errors emit {} and exit zero. See the adjacent README for setup."""
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
    log = pathlib.Path.home() / ".cache" / "approval-lens" / "probe-ask.log"
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
