# Engineering records

Current behavior is documented in the [README](README.md),
[configuration reference](docs/configuration.md) and
[architecture](docs/architecture.md). Product changes are in [CHANGELOG.md](CHANGELOG.md).

## Historical investigations

The original dated notes are preserved in [the engineering archive](docs/history/engineering-notes.md).
They include retired implementations and observations from specific host versions;
they are not current installation instructions or compatibility guarantees.

| Topic | Archive section |
| --- | --- |
| Claude Desktop reason rendering | Empirical results; M7 |
| Interactive CLI and headless behavior | M23: the CLI, both halves |
| Model-note errors and prompt/cache changes | M20–M23 |
| Engine extraction and remaining coupling | M26; M29–M31 |
| Rule guards and release review | M32 |

The archive predates the latest parser fixes and wording changes. Use the source
and tests for current behavior. No Codex, Cursor or OpenCode adapter has been
implemented or verified in this repository.

## Record a new host probe

Include the date, host version, surface (desktop, CLI or headless), plugin/config
version, exact input and observed result. Distinguish a tool call that was issued
from a request the agent declined to execute. Record where the explanation was
visible and whether an allowlisted call gained a prompt or failed.

Use the [live checklist](scripts/manual-test.md) for Claude Code and the
[adapter plan](docs/architecture.md#adding-codex-cursor-or-opencode) for future integrations.
