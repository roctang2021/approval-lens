# Approval Lens

**English** · [中文](README.zh.md)

[Installation](#installation) · [First use](#first-use) · [Model explanations](#model-explanations-optional)

**Understand before you approve.**

Even when full permissions are an option, users or company policies may require
approvals: routine actions can run automatically while others need confirmation,
or every action requires review.
But a dialog or terminal prompt may show only a command, a permission name or a
general reason, leaving the user unsure what approving it will actually do.

Approval Lens explains the pending action in plain language: what it does,
which files or services it affects, and what could change. The user can then
decide whether to approve or reject it.

Approval explanations are available in **6 languages**: English, Simplified
Chinese, Traditional Chinese, Japanese, Spanish and French.
[Choose your language](#language-and-sensitivity).

For example, you ask your agent to create a bootable drive, and this command
appears for approval (illustration only):

`sudo dd if=installer.img of=/dev/disk2 bs=4m`

Approval Lens could explain:

> 🔴 HIGH · This writes the installation image to disk /dev/disk2, overwriting
> existing data. Confirm this is the drive you want to make bootable; choosing
> the wrong disk could erase files or leave your system unable to start.

## Current support

Claude Code is the first integration. Codex, Cursor and OpenCode are planned.

| Agent | Status |
| --- | --- |
| Claude Code | Available: Bash, WebFetch, Write and Edit |
| Codex | Planned |
| Cursor | Planned |
| OpenCode | Planned |

The first version explains only actions that match a rule and reach the severity
threshold. Extending explanations to more existing approval prompts is a next
step; it does not yet explain every approval.

## Installation

These steps use a macOS or Linux terminal with [Claude Code 2.1.211 or later](https://code.claude.com/docs/en/quickstart).
Older versions can skip hook-requested confirmation in Auto mode; see
[Claude's hook behavior](https://code.claude.com/docs/en/hooks#pretooluse-decision-control).

### 1. Install uv

Skip this if `uv --version` already works. Otherwise, use the
[official uv installer](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reopen your terminal, then check both dependencies:

```bash
claude --version
uv --version
```

### 2. Install Approval Lens

Download the [source ZIP](https://github.com/roctang2021/approval-lens/archive/refs/heads/main.zip)
and unzip it. Open a terminal in the extracted folder containing this README and
`hooks/`, then run:

```bash
uv run --quiet hooks/approval_lens.py </dev/null >/dev/null
claude plugin marketplace add ./ --scope user
claude plugin install approval-lens@approval-lens --scope user
```

The first command prepares Python and PyYAML if needed. The remaining commands
install the plugin for your user across projects. Keep the source folder
in place for updates. You only need to install once; later sessions use your
usual `claude` command. No model API key is needed for the local rules.

## First use

1. Close any running Claude Code session and start `claude` in the project you
   want to work on.
2. Enter `/plugin`, open **Installed**, and confirm Approval Lens is enabled.
3. Use Claude normally. When an operation matches a high-risk rule, Approval
   Lens supplies an explanation at approval time. Read it, then approve or reject
   the operation using Claude's controls.

The default language is English and the threshold is **high**. Routine actions
may show no extra message.
If the plugin does not appear or no explanation is shown, see
[troubleshooting](docs/configuration.md#no-explanation-appears).

## Model explanations (optional)

For an explanation of the specific command and target, enable the model
integration. It currently uses an Anthropic API key and incurs API usage.

1. Create the settings folder:

   ```bash
   mkdir -p ~/.config/approval-lens
   ```

2. In your text editor, save your API key as a single line in
   `~/.config/approval-lens/api-key`, then restrict access:

   ```bash
   chmod 600 ~/.config/approval-lens/api-key
   ```

3. Create `~/.config/approval-lens/config.json` with the following. If the file
   already exists, merge the `llm` settings into it:

   ```json
   {
     "llm": {
       "enabled": true,
       "api_key_file": "~/.config/approval-lens/api-key"
     }
   }
   ```

Future matching approvals can include **What this does**. A missing key or
failed request leaves the local rule explanation in place. Set `enabled` to
`false` to turn model explanations off.

The model receives the command, URL or file path. Sending file content or user
request context requires separate settings. See [configuration and data handling](docs/configuration.md#enable-model-notes).

## Language and sensitivity

To use another language or include medium-risk actions, create or update
`~/.config/approval-lens/config.json`. These settings can coexist with `llm`:

```json
{
  "lang": "en",
  "ask": { "min_severity": "medium" }
}
```

Language codes: English (`en`), Simplified Chinese (`zh`), Traditional Chinese
(`zh-Hant`), Japanese (`ja`), Spanish (`es`) and French (`fr`). Changes take effect
on the next checked operation. See [all settings](docs/configuration.md#settings).

## What it checks

| Action in Claude Code | Examples of signals |
| --- | --- |
| Bash | Downloaded code execution, recursive deletion, credential paths, force-push, publishing |
| WebFetch | Credentials in URLs, secret-like parameters, IP or localhost targets |
| Write / Edit | Sensitive paths, startup scripts, Git hooks, download-and-execute or eval text |

Rules assign severity locally. At the threshold, the Claude adapter requests
confirmation and supplies a reason; this can add a prompt to an otherwise
auto-approved call. Below the threshold it returns no decision. It issues no
allow or deny decisions.

## Limits

- Coverage is rule-based. No warning does not establish that an action is safe.
- The shell parser handles common wrappers, pipelines and substitutions, but
  does not implement a full shell grammar or inspect downloaded code. It does
  not track a script downloaded and executed in separate steps.
- File-content rules match text; they do not determine whether that text will
  execute. MultiEdit and other unlisted tools are not covered.
- The host controls the final approval flow. Known headless Claude Code runs
  stay silent by default because nobody can answer a prompt. Hook failures
  leave native permission handling in place.
- Model notes can be wrong. Pattern filters catch some approval advice and
  safety claims; they do not guarantee factual accuracy.

## Status and development

```bash
uv run scripts/approval-lens-status.py   # Last check, daily counts and model-note status
./scripts/check.sh            # Tests, lint, hook smoke test and locales
```

[Configuration](docs/configuration.md) · [Architecture and planned integrations](docs/architecture.md) ·
[Updates and removal](docs/configuration.md#updates-and-removal) ·
[Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Engineering records](NOTES.md)

MIT · [License](LICENSE)
