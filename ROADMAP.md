# Development and release plan

**English** · [中文](docs/roadmap.zh.md)

Updated 2026-09-05. This is planned work, not a list of available features.

Approval Lens should help someone answer three questions before approving an
agent's action: what will it do, what will it affect, and what could change?
The priorities are clear explanations, a convenient installation, and useful
placement in the approval flow across Claude Code, Codex, Cursor and OpenCode.

## Starting point

Version **0.29.1** is public and installable from GitHub. Claude Code CLI and
live Anthropic API checks passed; the official Claude directory submission is
pending review. Six explanation languages are available. Desktop and IDE
surfaces still need manual acceptance. See the [release review](docs/release-review.md).

Two product gaps drive the next work: the current renderer can repeat the local
and model explanation, and the Claude hook can introduce a confirmation after
a rule match. It does not annotate every approval Claude would already show.

## Delivery order

Estimates assume one maintainer with agent assistance. They are working-day
timeboxes, except the final trial period. Host limitations, access to testers
and external review can change the schedule; versions below are proposed.

| Step | Target | Work | Completion condition | Estimate |
| --- | --- | --- | --- | --- |
| 1 | Publish 0.29.1 clearly | Direct GitHub installation, versioned Release, real demonstration and feedback instructions | A new user can install, find the plugin, update and remove it using the published instructions | 1–2 days |
| 2 | Verify approval access | Claude existing approvals; Codex first, then Cursor and OpenCode feasibility probes | Record where text can appear, whether an extra prompt is required, and select one additional host | 2–3 days |
| 3 | 0.30: clearer explanations | One concise body, reliable fallback, simpler setup and verified display surfaces | No duplicate explanation; target and consequences remain visible; approval behavior passes regression checks | 3–5 days |
| 4 | 0.31: second host | Implement the selected adapter and the shared boundaries it needs | One additional host passes installation and real approval-flow acceptance | 5–10 days after the probe |
| 5 | 1.0: stable supported scope | Early-user trial, fixes, upgrade guidance and release material | The release criteria below pass for every advertised host and surface | 1–2 weeks of trial, then fixes as needed |

Steps 1 and 2 can overlap. Step 3's copy work does not depend on a new host API.
Step 4 depends on step 2. Official directory review runs separately; neither
GitHub distribution nor development needs to wait for a listing.

## 1. Make the current release easy to try

- Make the already-tested GitHub marketplace commands the main installation
  path. Keep ZIP installation as an alternative. Verify first-run dependency
  preparation in a clean profile before changing the instructions.
- Create the 0.29.1 tag and GitHub Release after checking the release commit's
  CI. State the tested CLI scope, six languages, optional API cost and current
  approval coverage. Use “pending review” until the official listing is verified.
- Record a short real CLI demonstration and before/after images. Show a
  confusing operation, its target and a readable explanation. Analyze disk-write
  examples as data only; clearly label illustrations.
- Add a simple feedback template: host/version, language, expected meaning and
  observed text, with private details removed. Invite 5–10 early users and ask
  about understanding and installation friction. Do not collect commands or
  transcripts automatically.

## 2. Prove the integration before committing to it

For each probe, use one pending shell action and one routine allowed action.
Record the host version, surface, native permission mode, displayed text,
prompt count and the result of the user's decision. Test both model-off and
timeout behavior. This stage selects an integration; it does not ship four adapters.

| Host | Documented starting point | Question the probe must answer |
| --- | --- | --- |
| Claude Code | `PreToolUse` and `PermissionRequest` hooks | Can an explanation accompany an existing request without adding a confirmation or making the decision? |
| Codex | App-server approval requests handled by a client | Is there a supported extension point in the existing CLI/app? If only a separate client works, record that scope and effort explicitly. |
| Cursor | Execution hooks with `permission` and `user_message` | Does the message appear beside a pending approval, and can native policy remain intact? |
| OpenCode | The v2 permission evaluation hook exposes the decision and a message | Can an existing `ask` receive the explanation without changing its effect? Which released version and UI support it? |

Recommended investigation order is **Codex, Cursor, OpenCode**, alongside the
Claude check. Ship the first additional host with a verified, useful approval
surface and manageable installation. If Codex requires building a separate
client, publish the finding and move to Cursor or OpenCode for this iteration;
keep Codex on the roadmap without claiming native app support.

An “existing approvals” mode must add no prompts in the probe set and must not
change a permission decision. Where this is unavailable, document the limitation
and keep the current extra-confirmation behavior explicit. Do not implement an
automatic allow/deny response merely to display a reason.

These are documentation-based starting points, not verified integrations:
[Claude hooks](https://code.claude.com/docs/en/hooks#permissionrequest),
[Codex approval protocol](https://learn.chatgpt.com/docs/app-server#approvals),
[Cursor hooks](https://cursor.com/docs/hooks), and
[OpenCode v2 plugins](https://opencode.ai/v2/docs/build/plugins/).

## 3. Make each explanation worth reading

- Use a severity/target line and one concise explanation body. Combine the
  specific operation with distinct local risk information; avoid repeating the
  same effect. Keep rule evidence and severity independent of model wording.
- With the model off, explain what the local rules establish. With it on, add
  action-specific detail in the same place. Missing information stays unknown.
  Missing credentials, rejected requests and timeouts retain local explanations.
- Keep “AI generated” and provider labels out of the approval text. Explain
  model use, cost and transmitted data in setup and privacy documentation.
  File content and task context remain separate opt-ins.
- Provide a setup/check command for language, model settings and diagnostics.
  Preserve existing settings and keep credentials out of output and shell history.
- Check the installed CLI and the intended Desktop/IDE surfaces. Publish only
  the surfaces that pass. Keep all six locales aligned with the new layout.

Build a review set of at least 30 scenarios covering destructive changes, data
transfer, configuration edits, routine operations and missing context. Use it
to check target accuracy, misleading claims, repeated text and truncation.
Six-language rendering must pass; recruit fluent reviewers for translated copy
and record which languages have actually received that review.

Measure warm local latency and live-model latency separately. Initial targets
are local p95 below 300 ms and model p95 below 4 seconds on the recorded test
environment, with fallback at the configured model deadline. These are targets,
not guarantees; report sample size, cold-start cost and observed results.

## 4. Ship one additional host

Normalize action type, command/target, available context and host capabilities
at the adapter boundary. Reuse parsing, rules and localized text. Keep host
transcript handling, rendering, model-provider calls and local storage behind
explicit interfaces; extract only what Claude and the selected adapter need.

Verify supported action types, allowlisted and denied operations, accept/reject,
non-interactive runs, cancellation, parallel requests and model failure. The
explanation must correspond to the exact pending action. Re-run Claude's
regression suite and document installation, upgrade, removal and unsupported
surfaces for the new host before announcing support.

## 5. Release a stable supported scope

The 1.0 decision is based on the advertised experience, not all four adapters
being complete. GitHub Releases and the official directory can distribute
earlier versions; 1.0 is our maintenance and compatibility milestone.

- All advertised hosts/surfaces pass the relevant automated and real-flow checks.
- No known defect reverses the user's decision, hides a pending approval or
  gives a materially misleading explanation in the reviewed scenario set.
- Target: at least 4 of 5 trial users install without maintainer intervention
  and correctly explain the action and target in three sample approvals.
- Upgrade and removal work, and release notes identify configuration changes,
  limitations and the previous usable version.
- The README, demo, privacy statement and marketplace description match what
  the released version does. Address directory feedback when it arrives; check
  submission status weekly without duplicate submissions. Review timing is
  controlled by Anthropic, whose [guide](https://claude.com/docs/plugins/submit)
  gives no fixed turnaround.

Implementation, tests, documentation and release preparation can be done with
agent assistance. The maintainer owns scope choices and tester recruitment;
trial users provide comprehension feedback, and Anthropic owns listing approval.

## After the first stable release

Add the remaining Codex, Cursor and OpenCode adapters using the same feasibility
and acceptance process. Keep host support separate from model-provider support.
Prioritize an OpenAI-compatible or organization-managed endpoint when early
users need it; validate its data handling and fallback before release.

Defer a hosted dashboard, SSO, billing, a separate website/domain and additional
languages until demand justifies their maintenance. The immediate measures of
progress are successful installations and understandable approvals.
