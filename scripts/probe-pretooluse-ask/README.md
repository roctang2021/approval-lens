# Probe: PreToolUse `"ask"` — where does the reason render?

## Question

The PermissionRequest `systemMessage` route is dead on Desktop (verified
2026-07-19, see NOTES.md § "systemMessage rendering"). The remaining candidate
surface is the **PreToolUse** hook's `permissionDecision: "ask"`:

- Docs (hooks § PreToolUse decision control): for `"allow"` and `"ask"`,
  `permissionDecisionReason` is *"shown to the user but not Claude"* — but the
  docs don't say **where** (dialog vs transcript).
- Docs also say an `"ask"` prompt carries an origin label (`[Project]`,
  `[Plugin]`, …), and CHANGELOG 2.1.211 says a hook `ask` "floors the decision
  at a prompt" — i.e. it forces a dialog even for otherwise auto-allowed calls.

If the reason renders on the dialog, Permission Lens can move its annotation
there (severity-gated, still never allow/deny). This probe answers that with
the same instrumented-hook method as the systemMessage probe.

## Setup (scratch project — plugin and global settings untouched)

```bash
D=~/Code/oss/pl-ask-probe   # somewhere Finder can see — /tmp is hidden from GUI pickers
mkdir -p "$D/.claude"
cat > "$D/.claude/settings.json" <<EOF
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash|WebFetch", "hooks": [
        { "type": "command",
          "command": "python3 $HOME/Code/oss/permission-lens/scripts/probe-pretooluse-ask/probe.py",
          "timeout": 10 } ] }
    ]
  }
}
EOF
echo "$D"
```

Open `$D` as a project in the Desktop app (approve the project-hook trust
prompt), then ask Claude to run `ls -la`. Repeat once in a terminal `claude`
session in `$D` — last time the CLI never fired the *plugin* hook, so a
settings-registered hook is a useful second data point.

## Record in NOTES.md (§ Empirical results)

1. Marker text: on the dialog itself, near it, transcript only, or nowhere?
   Both lines (multi-line), or collapsed to one?
2. Origin label (`[Project]`/`[Local]`) shown?
3. Native Allow / Deny both still work?
4. Floors-at-a-prompt: click "always allow" for `ls`, run it again — does the
   dialog still appear (with the marker)?
5. `~/.cache/permission-lens/probe-ask.log` has an `IN:`/`OUT:` pair per
   invocation (proof of firing even if nothing renders); CLI vs Desktop both?

## Cleanup

Delete the scratch dir (`rm -rf $D`) and, if you're done probing, the log:
`rm -f ~/.cache/permission-lens/probe-ask.log`.
