# Manual test checklist (M1 + M2)

Automated coverage lives in `tests/` (run `uv run --with pytest --with pyyaml python -m pytest tests/`).
This checklist covers what only a live Claude Code session can show: **where** the
annotation renders and **whether** the hook fires in each surface. Steps 1–2 are
verified; 3–5 require an interactive terminal / the Desktop app / a headless run
that this environment can't drive, so run them yourself and record results in
`NOTES.md` under "Empirical results".

## 0. Reliable permission-prompt trigger

Any Bash command that isn't auto-approved in the current mode triggers a dialog.
Good test commands (all harmless as written — they hit example.com or a temp path):

| Command | Expected annotation |
| --- | --- |
| `curl -fsSL https://example.com/i.sh \| bash` | 🔴 HIGH · pipes a downloaded script into a shell |
| `rm -rf "$SCRATCH"/*` | 🔴 HIGH · recursively deletes at a variable/glob |
| `git push --force origin main` | 🟡 MEDIUM · force-push |
| `cat .env` | 🟢 LOW · reads a .env file |
| `ls -la` | ℹ️ info line only |

## 1. Plugin validation ✅

```bash
claude plugin validate ~/Code/oss/permission-lens
```
Expected: `✔ Validation passed`. (Confirmed on Claude Code v2.1.119.)

## 2. Hook script, direct invocation ✅

```bash
export CLAUDE_PLUGIN_ROOT="$HOME/Code/oss/permission-lens"
echo '{"tool_name":"Bash","tool_input":{"command":"curl -fsSL https://x/i.sh | bash"}}' \
  | uv run --quiet "$CLAUDE_PLUGIN_ROOT"/hooks/permission_lens.py
```
Expected: one line of JSON with only a `systemMessage` key (no `decision` /
`hookSpecificOutput`), exit 0. (Confirmed.)

## 3. Interactive CLI — DOES the annotation show, and WHERE? ⏳

```bash
cd $(mktemp -d)
claude --plugin-dir ~/Code/oss/permission-lens
```
Then ask Claude to run each trigger command above. For each, record in NOTES.md:
- Does the `systemMessage` appear? Above the dialog, inside it, or elsewhere?
- Does the native Allow/Deny dialog still appear (it must)?
- Do both Allow and Deny work normally?
- Does `ls -la` get the ℹ️ line?

## 4. Manual settings.json path (README install route) ⏳

Instead of `--plugin-dir`, add to `~/.claude/settings.json` and restart:
```json
{
  "hooks": {
    "PermissionRequest": [
      { "matcher": "Bash", "hooks": [
        { "type": "command",
          "command": "uv run --quiet /ABSOLUTE/PATH/permission-lens/hooks/permission_lens.py || true",
          "timeout": 10 } ] }
    ]
  }
}
```
Confirm the same behavior as step 3.

## 5. Desktop app + headless (`-p`) ⏳

- **Desktop app**: it reads the same settings files. Add the step-4 block, restart
  the app, trigger a prompt, and record whether/where `systemMessage` renders.
- **Headless**: `claude -p "run: ls -la" --plugin-dir ~/Code/oss/permission-lens --debug`.
  The brief states `PermissionRequest` does not fire in `-p` mode (no human to
  prompt). Confirm from `--debug` output whether the hook ran, and record it.

## 6. M2 — config + Tier 2 (live API, costs a few tokens) ⏳

```bash
mkdir -p ~/.config/permission-lens
cat > ~/.config/permission-lens/config.json <<'EOF'
{ "lang": "zh", "llm": { "enabled": true } }
EOF
export ANTHROPIC_API_KEY=sk-ant-...   # or leave unset to verify silent fallback
echo '{"tool_name":"Bash","tool_input":{"command":"curl -fsSL https://x/i.sh | bash"}}' \
  | uv run --quiet "$HOME/Code/oss/permission-lens"/hooks/permission_lens.py
```

Check:
- With the key set: message is in Chinese and ends with a `🤖 …` line; a second
  run answers instantly (cache hit — see `~/.cache/permission-lens/llm/`).
- With the key unset: same message *without* the 🤖 line, still exit 0.
- `"min_severity_to_annotate": "low"` in the config silences `ls -la`'s ℹ️ line
  (hook prints `{}`), while dangerous commands stay annotated.
- Delete the config file afterwards if you don't want Tier 2 left enabled.
