# Release review — 0.29.1

Reviewed 2026-09-05. Source is public at
[roctang2021/approval-lens](https://github.com/roctang2021/approval-lens).
Interactive CLI and live model checks are recorded below. These product checks
are separate from Anthropic's plugin-directory review.

## Fixed in this review

| Finding | Change |
| --- | --- |
| Model response files inherited a typical `0644` mode and could expose input details to other local accounts | Cache directories are restricted to their owner on use; new responses use private temporary files and atomic replacement |
| A zero cache lifetime could still reuse a same-tick or future-dated entry; non-finite timestamps could evade expiry | Zero skips reads and writes; invalid and future timestamps are cache misses |
| Targets and model text retained terminal and bidirectional control characters | Approval text renders these characters as visible escapes; ordinary multilingual text and emoji are preserved |
| Installation guidance omitted an Auto-mode compatibility requirement | Both READMEs now require Claude Code 2.1.211 or later |
| The documented local marketplace source `.` was rejected by Claude Code 2.1.233 | Both READMEs use `./`; the exact installation commands passed in an isolated profile |
| Checks validated only the marketplace, and CI skipped Claude validation without a CLI | Both manifests are validated; CI installs the locally reviewed CLI version |
| Subprocess tests and smoke checks could inherit headless behavior from the invoking agent | Tests set the intended surface explicitly; the full suite passes when launched with a headless entrypoint |

The version requirement follows [Claude's documented hook behavior](https://code.claude.com/docs/en/hooks#pretooluse-decision-control).
The default `claude-sonnet-5` ID is listed in the [official model catalog](https://platform.claude.com/docs/en/models/overview).

## Verification completed

Environment: macOS arm64, Claude Code 2.1.233, uv 0.11.7, Python 3.13.

- **672 automated tests passed**, including 20 new cache and display regressions.
- Static checks, documentation links and JSON/shell example syntax passed.
  Example commands were parsed as data or checked with `bash -n`, never executed.
- Both marketplace and plugin manifests passed Claude's strict validation.
- An isolated Claude profile installed Approval Lens 0.29.0 using the README's
  commands from a source folder containing spaces. The installed version, renamed
  entry point, status command and plugin update check passed.
- **120 installed-hook cases passed**: six languages, Bash/WebFetch/Write/Edit,
  ordinary silent calls, and interactive plus three recognized headless entrypoints.
  The isolated plugin was uninstalled afterward; the real user profile was unchanged.
- The README's source ZIP downloaded without authentication. The downloaded copy
  passed the same installation, 120 hook cases, status, update and uninstall checks.
- [Ubuntu and macOS CI passed](https://github.com/roctang2021/approval-lens/actions/runs/34007958195)
  on the first public source commit, including both strict manifest validations.
- The complete source, including archived notes, had no matches for the checked
  common Anthropic/GitHub token or private-key formats. This was a pattern scan.

The automated tests use mocked model requests. The following checks used real
Claude Code sessions and the Anthropic API.

## Live acceptance completed

Tested on macOS with Claude Code 2.1.233, using a temporary workspace and plugin
configuration. Interactive terminal prompts were observed through a PTY.

| Check | Observed result |
| --- | --- |
| Install `roctang2021/approval-lens` as a GitHub marketplace in an isolated profile | Version 0.29.0 installed and enabled; the test copy was uninstalled |
| Manual mode, English, model off | Rule explanation and target appeared; No stopped the action, Yes ran the requested probe |
| Routine `ls -la` in manual mode | Ran without an Approval Lens confirmation |
| Auto mode, Chinese, model enabled without a key | Chinese rule explanation appeared; No stopped the action, Yes ran the probe; status recorded `no_credential` |
| Auto mode, English, 0.29.1 with a live API key | The real prompt included the model explanation after `What this does`; No stopped the action |
| Six languages, device-write text analyzed through the full hook | All returned model notes; the final six calls took 1.70–3.10 seconds each and none was truncated |
| URL and file-path model notes | URL note omitted the dummy password; path-only note stated that changes were unknown; opting in to dummy file content described the supplied change |
| API rejection and a 0.1-second deadline | Both retained the local explanation and returned `ask`; observed hook times were 0.23 and 0.17 seconds |

Live execution probes used a reserved `.invalid` hostname. Approved attempts
failed DNS resolution and supplied no script to execute. Device-write examples
were passed only as JSON text to the analyzer; no disk-writing command ran.
After one denial, Claude declined a repeat request before calling the hook;
that attempt was excluded, and the separate approval case used another
reserved hostname.

The first model pass exposed excessive length, overstated disk erasure/recovery
claims and a guessed identity from a file path. Version 0.29.1 narrows prompts to
one sentence and supported effects. The final reviewed samples corrected those
issues. This does not guarantee all future model responses will be accurate.

The remaining UI coverage is Claude Desktop and IDE surfaces. They have not been
manually checked. These results cover the interactive CLI; use the
[live checklist](../scripts/manual-test.md) when adding another surface. The
README's disk-writing example remains an illustration.

## Official directory submission

The public repository is installable through its own marketplace. Listing in
Anthropic's official directory requires a separate submission and review.

[Anthropic's submission guide](https://claude.com/docs/plugins/submit) calls for
a public GitHub repository, plugin validation and compliance with its directory
terms and policy. It does not list a stable-release label, a GitHub Release or a
1.0 version number as a submission prerequisite. Passing local checks does not
guarantee acceptance or an Anthropic Verified badge.

Individual authors can submit through the
[Console form](https://platform.claude.com/plugins/submit) with a Developer,
Admin or Owner role in a Console organization. This repository has not yet
been submitted to the official directory.

## Scope to retain in release copy

Claude Code is available; Codex, Cursor and OpenCode are planned. The current
version explains rule matches above the threshold and can add a confirmation
request. It does not annotate every existing approval.

The proposed shorter layout that combines the rule and model explanation into
one body is still pending. Current rendering appends the model note and can
repeat the rule's effect. Keep this in the preview feedback plan alongside
native-language review of the six translations.
