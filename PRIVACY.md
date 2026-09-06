# Privacy and data handling

Updated September 5, 2026. This notice covers Approval Lens 0.29.1.

Approval Lens runs on your computer. It has no maintainer-operated backend,
analytics service or user accounts. The maintainer does not receive the actions
you analyze through normal plugin use.

## Local analysis

The plugin reads the command, URL, file path and supplied new content from
Claude Code's hook event to identify matching rules. Local rule analysis does
not send those inputs to a model or to the maintainer. Installing the plugin
and its dependencies may contact GitHub and package providers. Claude Code's
own handling of your session is separate from this plugin.

## Optional model explanations

Model explanations are off by default. When enabled, matching operations send
the command, URL or file path to Anthropic's Messages API using your API key.
These strings can contain private information or credentials; Approval Lens
does not automatically remove them before sending.

File content and the latest available user request are separate opt-ins.
`send_file_content` includes Write content or Edit replacement text;
`send_task_context` reads the Claude Code transcript and includes up to 400
characters of the latest available user request. Neither option is enabled
by default. The plugin does not add your working directory or session ID to
the model request.

Anthropic processes API requests under its applicable terms and
[privacy policies](https://www.anthropic.com/legal/privacy).
The plugin cannot delete information already sent to Anthropic. For provider
data questions or requests, use Anthropic's privacy channels.

## Local storage and controls

- Settings and any configured key file stay on your computer. The API key is
  sent to Anthropic for authentication; it is not part of the model prompt.
- Model responses are cached under `~/.cache/approval-lens/llm/` by default.
  Cached text can repeat details from the input. Cache directories and new
  response files are restricted to their owner when used.
- The default seven-day cache lifetime controls reuse, not deletion. Old files
  can remain until you remove them. Setting `cache_ttl_days` to `0` disables
  reads and writes but does not erase existing files.
- `heartbeat.json` records local timestamps, version, tool names, counters,
  severity and outcomes. It excludes commands, URLs and file paths.
- Optional debug logs can contain paths and error details. Review them before
  sharing. Debug logging is off by default.

Set `llm.enabled` to `false` to stop future model requests. Remove the cache
directory to clear local responses and status. Uninstalling the plugin leaves
your settings, key file and cache in place; remove them separately if desired.
See [configuration](docs/configuration.md#data-handling) for settings and path
overrides.

## Contact

Use [GitHub Issues](https://github.com/roctang2021/approval-lens/issues) for
general questions; issues are public, so omit private information. Report
security issues through the [private reporting channel](SECURITY.md).

Changes to data handling will be recorded in this notice and the changelog.
