# Claude PreToolUse rendering probe

This standalone hook always returns `ask` with a two-line marker. Use it to
check where a host version displays `permissionDecisionReason` and whether it
preserves line breaks. It is not part of the installed plugin.

The probe logs complete input and output to
`~/.cache/approval-lens/probe-ask.log`. Use only test data: tool inputs can
contain credentials. An ask can fail a call in a headless session.

## Run in a scratch project

Create a new project directory and add `.claude/settings.json` with:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "python3 \"/ABSOLUTE/PATH/approval-lens/scripts/probe-pretooluse-ask/probe.py\"",
        "timeout": 10
      }]
    }]
  }
}
```

Replace the path, open that project in Claude Code and ask it to run `ls -la`.
Record the host version and surface, marker location, line breaks, approval
options and whether the log contains the invocation. Repeat in an interactive
CLI session if comparing surfaces. Past results are in the
[archive](../../docs/history/engineering-notes.md).

Remove this hook from the scratch settings when finished. Delete the probe log
when you no longer need the recorded input.
