# Architecture and integrations

Approval Lens helps users understand a coding agent's action at the point of
approval. It serves individuals and teams that retain selective or manual
approval, where a raw command or general permission description may not explain
what will happen. The product is intended for multiple agents; Claude Code is
the first implemented adapter.
Codex, Cursor and OpenCode are planned. There is no implementation order or
release date for those adapters yet.

## Intended experience and current scope

An explanation should answer what the action does, which files or services it
affects, and what changes matter to the person approving it. With user-provided
task context, it can also explain the apparent connection to the request.
The user retains the approval decision.

Model explanations are central to making the text specific to each action.
Local rules provide consistent risk signals and a fallback when a model is
unavailable. Context must be supplied with consent; the model should state
uncertainty when the operation alone does not establish its purpose.

The current Claude adapter generates explanations only after a risk-rule match
passes the severity threshold. Its PreToolUse `ask` response can introduce a
confirmation request. It does not observe and annotate every approval the host
would otherwise show. Covering those existing prompts, with minimal extra
interruptions, is a product requirement still to implement and verify per host.

Next integration work should prioritize access to pending approvals, concise
explanations beside the decision controls, and bounded model latency with a
local fallback. Where the host permits it, additional detail can be available
on demand. Evaluate clarity, factual correctness and added waiting time as well
as rule coverage. More supported model providers and team-managed endpoints
are future options; the current provider is Anthropic.

## Current code

| Area | Responsibility |
| --- | --- |
| `hooks/approval_lens.py` | Claude Code event input, interactive/headless detection and hook response |
| `hooks/lens/core.py` | Dispatch, severity threshold, optional note and rendered assessment |
| `parsing.py`, `rules.py`, `predicates.py` | Shell structure, rule matching and matching evidence |
| `detail.py`, `render.py`, `locales.py` | Target extraction and localized explanation |
| `config.py`, `tier2.py`, `heartbeat.py` | Settings, Anthropic API/cache and local status |
| `context.py` | Optional user-request lookup in a Claude Code transcript |

`assess(event, config, surface)` returns `Assessment(matches, asked, reason,
tier2_outcome)`. `build_message()` also records a heartbeat and returns the reason.
`config` comes from `load_config()` or `validate_config()`.

## What is reusable today

Shell parsing, risk rules, matching evidence and localized explanations can be
shared. Host event delivery and approval behavior belong in adapters.

The separation is incomplete: the engine currently accepts Claude-shaped tool
names and fields, `context.py` reads Claude transcript records, and optional
model notes use Anthropic directly. Assessment can read files, environment
settings and cache data, and can make a network request when enabled. It is not
a pure function. These dependencies need explicit boundaries before claiming a
host-independent API.

## Adding Codex, Cursor or OpenCode

1. Define a shared action input for shell commands, URLs, file writes and edits.
   Normalize each host's names and fields at its adapter boundary.
2. Supply optional user context through the adapter, retaining separate consent
   for sending it to a model. Keep transcript parsing out of shared analysis.
3. Verify the host's extension points: when interception runs, whether a reason
   can appear beside approval, and how allowlists and headless runs behave.
   Record host version, surface, input and observed output.
4. Implement and test that host's response mapping. Publish support only for
   tool types and surfaces that have been exercised end to end.

The product objective is consistent explanations across agents. The host may
require a different delivery surface; support for native-dialog annotations
must be verified separately for each integration. Selecting a coding agent
and selecting a provider for optional model notes are separate concerns.

## Shared behavior

Rules determine severity. Generated text can supplement an explanation but
cannot change the assessment. Missing information should remain uncertain;
no match is not a safety verdict. Optional services and diagnostics should
fail without substituting an approval decision.

The Claude adapter currently emits only `ask` or `{}` and exits zero for handled
errors. Known headless entrypoints default to silence. Future adapters need
host-specific tests for equivalent behavior, rather than reusing Claude's wire
format or assuming that asking always produces an interactive dialog.

[Contributing](../CONTRIBUTING.md) · [Historical probes](../NOTES.md)
