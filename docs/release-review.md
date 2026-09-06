# Release review — 0.29.0 candidate

Reviewed 2026-09-05. Source is public at
[roctang2021/approval-lens](https://github.com/roctang2021/approval-lens).
This is a preview; a stable release still needs the live acceptance checks below.

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

These checks establish installation and hook output behavior. They do not prove
that a native dialog was displayed or that a live model explanation was useful.
Model requests in automated tests were mocked; no live model API calls were made.

## Remaining acceptance

Follow the [live checklist](../scripts/manual-test.md) on the intended Claude
surfaces: verify readable reasons and approval/rejection in manual and Auto
modes, then exercise a real model request, locale selection and fallback.
Record host version, observed text and waiting time. The README's disk-writing
example is an illustration, not captured model output.

Keep 0.29.0 marked as unreleased until live acceptance is complete.

## Scope to retain in release copy

Claude Code is available; Codex, Cursor and OpenCode are planned. The current
version explains rule matches above the threshold and can add a confirmation
request. It does not annotate every existing approval.

The proposed shorter layout that combines the rule and model explanation into
one body is still pending. Current rendering appends the model note and can
repeat the rule's effect. Keep this in the preview feedback plan alongside
native-language review of the six translations.
