# Changelog

User-visible changes by version. Investigation details are in the
[engineering archive](docs/history/engineering-notes.md).

## 0.29.0 (unreleased)

- Renamed the project from Permission Lens to Approval Lens before public
  distribution. Plugin IDs, script names, settings/cache paths and environment
  variables now use the new name.
- Restricted model response caches to their owner. Disabling caching now skips
  existing entries, and invalid or future timestamps trigger a fresh request.
- Escaped terminal and bidirectional control characters in approval text.
- Documented Claude Code 2.1.211 as the minimum version for Auto-mode prompts.
  Checks now validate both manifests, documentation links and example syntax,
  and fix the smoke-test surface. CI installs the reviewed Claude CLI.
- Fixed missed risks in wrapped commands, nested shell strings, connected
  pipelines and unquoted heredoc substitutions. Guards now apply to the matching
  stage and honor effective dry-run values.
- Reduced false positives from quoted command examples and unrelated stages.
  Target details now come from the action that matched the rule.
- Added rules for device redirection, GitHub repository deletion, additional
  credential paths, Kubernetes deletion and privileged containers. Expanded
  file-upload and force-push detection.
- Fixed `approval-lens-status` for filtered model notes and localized its output.
- Model notes now accept API keys only. Removed OAuth credential resolution;
  legacy `llm.auth_token_env` and `llm.auth_token_file` settings are ignored.
- Shortened risk text and model prompts in all six languages. Removed unsupported
  claims about public visibility, recovery and intent.
- Replaced the parenthesized AI label with "What this does" and its localized
  equivalents. Model source and data handling remain in configuration guidance.
- Reorganized English and Chinese guides around setup and use. Documented Claude
  Code as the first integration, with Codex, Cursor and OpenCode planned.
  Configuration and architecture now have separate references.
- Clarified the focus on understanding actions at approval time, with model
  explanations for specific operations. Documented the gap between current
  rule-triggered prompts and broader coverage of existing approvals.
- Added persistent folder installation, first-use steps, model key-file setup,
  and update/removal instructions to the English and Chinese guides. Verified the
  local marketplace source `./` with Claude Code 2.1.233.
- Aligned sample configuration with defaults and added Ubuntu/macOS CI checks.

## 0.28.x (2026-08-14)

- Split the Claude entry point from the `hooks/lens/` package. Tool-field and
  transcript dependencies remain; see [architecture](docs/architecture.md).
- Added opt-in diagnostics for unexpected handled errors and contribution guidance.

## 0.26.0 (2026-08-14)

- Added patterns that omit model notes containing safety verdicts or approval
  advice. These filters do not guarantee factual accuracy.

## 0.25.0 (2026-08-14)

- Added structural rule guards, argument/redirect scopes and dry-run handling.

## 0.23.0 to 0.24.0 (2026-08-14)

- Added `|&` pipelines and analysis of shell input passed through ssh heredocs.
- Made interactivity and model outcomes explicit assessment inputs/results.

## 0.20.0 to 0.22.0 (2026-08-14)

- Known headless runs default to silence.
- Changed model defaults to `claude-sonnet-5` and a 5-second deadline. Removed
  notifications and included the system prompt in response cache keys.
- Added generated analysis examples and documentation checks.

## 0.12.0 to 0.16.0 (2026-07-25 to 2026-08-14)

- Reduced matches on quoted examples and inert heredoc content.
- Added concrete targets and a labeled, parenthesized model note.

## 0.9.0 to 0.11.1 (2026-07-19 to 2026-07-25)

- Added opt-in task context, model status reporting, credential-path rules for
  file operations and single-line reason formatting.

## 0.8.0 and earlier (2026-07-18 to 2026-07-19)

- Added Claude PreToolUse explanations, offline rules for Bash/WebFetch/Write/Edit,
  optional model notes, local status and six languages.
