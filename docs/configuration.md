# Configuration — Claude Code integration

[English](configuration.md) · [中文](configuration.zh.md) · [README](../README.md)

Create `~/.config/approval-lens/config.json`. Missing or invalid values use
per-key defaults; numeric values are clamped to their supported ranges.
See [config.example.json](../config.example.json) for the complete shape.

Earlier local previews used the name Permission Lens. If you used one, reinstall
under the Approval Lens plugin name and copy any settings you want to retain to
`~/.config/approval-lens/config.json`. Update a configured key-file path as needed.

## Settings

| Key | Default | Accepted values / effect |
| --- | --- | --- |
| `lang` | `en` | `en`, `zh`, `zh-Hant`, `ja`, `es`, `fr`; affects dialogs, model language and status |
| `ask.min_severity` | `high` | `low`, `medium`, `high`; matches at or above this level request confirmation |
| `ask.non_interactive` | `silent` | `silent` or `ask`; requesting confirmation without a user can fail the tool call |
| `max_message_chars` | `500` | 80–9000 characters |
| `llm.enabled` | `false` | Literal `true` enables model notes |
| `llm.model` | `claude-sonnet-5` | Model ID sent to the Anthropic Messages API; choose one available to your account |
| `llm.timeout_seconds` | `5.0` | 0.1–6.0 seconds; time spent waiting before falling back to rule text |
| `llm.api_key_env` | `ANTHROPIC_API_KEY` | Environment variable holding your API key |
| `llm.api_key_file` | empty | Optional key file; used when the environment key is absent |
| `llm.cache_ttl_days` | `7` | 0–365 days; 0 disables cache reads and writes |
| `llm.send_file_content` | `false` | Also send Write content or Edit new_string to the model |
| `llm.send_task_context` | `false` | Also send the last available user request from the Claude Code transcript, capped at 400 characters |

The adapter identifies known headless entrypoints from `CLAUDE_CODE_ENTRYPOINT`
(`sdk-cli`, `sdk-py`, `sdk-ts`). Missing or unknown values use interactive behavior.

## Enable model notes

Enable model explanations to describe the specific command and target at the
point of approval:

```json
{
  "llm": {
    "enabled": true,
    "api_key_file": "~/.config/approval-lens/api-key"
  }
}
```

Put your API key on a line in that file and restrict access with `chmod 600`.
The environment variable takes precedence. A key file is useful when a GUI app
does not inherit your shell environment. The integration accepts API keys;
it does not reuse your coding agent's subscription login.

To help explain the connection to your task, separately set
`"send_task_context": true` under `llm`; this sends the latest available user
request. Explaining file changes also requires `"send_file_content": true`.
Otherwise, the model receives only the file path.

Only rule matches that reach the confirmation threshold use the model. Enabling
it does not expand approval coverage. A missing key, API error or timeout leaves
the rule explanation in place.

## Data handling

- Local rules inspect the command, URL, file path and supplied new content.
- Model notes send the command, URL or path to Anthropic. These strings may
  already contain credentials. File contents and the user request are separate
  opt-ins; cwd and session ID are not added to the request.
- Model responses are cached under `~/.cache/approval-lens/llm/`. Filenames
  are hashes of the inputs and prompt; cached text can include details from
  those inputs. The cache directory is restricted to its owner when used, and
  new response files have owner-only read/write permissions. Changing the prompt
  changes the cache key. Setting `cache_ttl_days` to 0 leaves existing files on
  disk; remove this `llm/` directory to clear saved responses.
- `heartbeat.json` stores timestamps, version, tool name, counts, severity and
  outcome. It does not store command text, URLs or file paths.
- `APPROVAL_LENS_DEBUG=1` enables local diagnostic logs. Logs can include
  paths and error details. Remove sensitive details before sharing them.

For testing, `APPROVAL_LENS_CONFIG` overrides the config path and
`APPROVAL_LENS_CACHE_DIR` overrides the cache directory.

## Manual hook installation

Use this only if you have not installed through the plugin manager and are not
loading with `--plugin-dir`. Merge the
following into `~/.claude/settings.json`, replace the absolute path, and restart
Claude Code. Configure the hook once to avoid duplicate invocations.

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash|WebFetch|Write|Edit",
      "hooks": [{
        "type": "command",
        "command": "sh -c 'command -v uv >/dev/null 2>&1 || PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"; uv run --quiet \"/ABSOLUTE/PATH/approval-lens/hooks/approval_lens.py\"' || true",
        "timeout": 10
      }]
    }]
  }
}
```

The PATH fallback locates uv in common GUI installations. `|| true` prevents a
launcher failure from returning a blocking exit code to Claude Code.

## Updates and removal

For the folder installation in the [README](../README.md#installation), replace
the source folder's contents with the new release, then run:

```bash
claude plugin marketplace update approval-lens
claude plugin update approval-lens@approval-lens --scope user
```

Start a new Claude Code session to load the update. Keep the source folder at
the registered location so the marketplace can find it.

To stop using the plugin, run:

```bash
claude plugin uninstall approval-lens@approval-lens --scope user
```

Then start a new session. Your Approval Lens config and API key file remain;
remove those files separately if you no longer need them.

Installation scopes and plugin management follow
[Claude Code's plugin workflow](https://code.claude.com/docs/en/discover-plugins).

## Local development preview

From the repository root, load a session directly from the working copy:

```bash
claude --plugin-dir "$PWD"
```

This applies to that launch; repeat the flag for later previews. Avoid loading
both an installed copy and this working copy in the same session. Use the
[developer checklist](../scripts/manual-test.md) to inspect hook output or
exercise a live dialog.

## No explanation appears

Run `claude plugin list` and confirm `approval-lens@approval-lens` is enabled.
If it is absent, repeat [installation](../README.md#installation) from the source
folder. If it is disabled, enable it in `/plugin` and start a new session.
If your organization blocks custom marketplaces, ask its administrator to
approve or distribute the plugin.

Run `uv --version` in a fresh terminal. If uv is missing, install it and restart
Claude Code. Then run `uv run scripts/approval-lens-status.py` from the source folder.
Check whether a call was
recorded, its severity, and the running version. Below-threshold calls and known
headless runs are normally silent. If no check was recorded, confirm the plugin
is loaded and uv can start. If versions differ, update the installed plugin or
reload the local plugin session as appropriate.

For dialog behavior, use the [live checklist](../scripts/manual-test.md).
