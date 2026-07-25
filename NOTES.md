# NOTES — hooks-schema verification & design decisions

## Step 0: docs verified 2026-07-18

Sources (authoritative, re-check before schema changes):

- Hooks reference: https://code.claude.com/docs/en/hooks
- Permission modes: https://code.claude.com/docs/en/permission-modes
- Plugins reference: https://code.claude.com/docs/en/plugins-reference

### Confirmed facts we depend on

1. **`PermissionRequest` input** (docs § "PermissionRequest input"): stdin JSON with
   `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`,
   `tool_name`, `tool_input` (for Bash: `{command, description}`), and an **optional**
   `permission_suggestions` array (the dialog's "always allow" options).
   There is **no `tool_use_id`** on this event (PreToolUse has it; PermissionRequest
   explicitly does not — matches the project brief).
   - **Per-tool `tool_input` fields** *(needed for M5; the hooks reference page
     documents only the Bash shape, so these were verified empirically from real
     session transcripts under `~/.claude/projects/*/*.jsonl` on 2026-07-19 —
     a tool_use block's `input` is exactly what arrives as the hook's
     `tool_input`)*:
     - **WebFetch**: `{url, prompt}`
     - **Write**: `{file_path, content}`
     - **Edit**: `{file_path, old_string, new_string, replace_all}`
     - **MultiEdit**: not present in any local transcript → unverified → NOT
       covered by M5 (would need `{file_path, edits:[...]}` confirmed first).
2. **Passthrough**: a decision requires
   `hookSpecificOutput: {hookEventName: "PermissionRequest", decision: {behavior: …}}`.
   Omitting `hookSpecificOutput` and returning only common fields (`systemMessage`)
   means *no decision* → the native dialog still shows. This is the core mechanism
   Permission Lens relies on.
3. **`systemMessage`** (docs § "JSON output"): common output field, "warning message
   shown to the user"; user-facing only — the model does not see it. All hook output
   strings are capped at **10,000 chars** (overflow is written to a file and replaced
   with a preview). We target ≤ 500 chars.
4. **Exit codes** (docs § "Exit code 2 behavior per event"): on `PermissionRequest`,
   **exit 2 DENIES the permission**. Therefore:
   - the script exits 0 on every code path, including internal errors (prints `{}`);
   - the hooks.json command has an `|| true` guard so a failing launcher (`uv`
     itself can exit 2 on usage errors) can never deny on the user's behalf.
5. **JSON parsing**: on exit 0, stdout is parsed as JSON if valid; *invalid* JSON on
   exit 0 is treated as plain text rather than an error. We still emit exactly one
   JSON object and nothing else.
6. **Plugin format** (plugins reference): manifest at `.claude-plugin/plugin.json`
   (only `name` required); hooks auto-discovered at `hooks/hooks.json`;
   `"${CLAUDE_PLUGIN_ROOT}"` path substitution (keep it quoted); hook `timeout` is in
   **seconds** (default 600 — we set 10 explicitly). Dev loop:
   `claude --plugin-dir <dir>`; validation: `claude plugin validate . --strict`.

### Discrepancies / gaps vs the project brief

- The brief states `PermissionRequest` does not fire in non-interactive (`-p`) mode.
  The docs do **not** state this explicitly (they only document `-p` behavior for
  other events). → verify empirically; results below.
- The docs do not specify *where* `systemMessage` renders relative to the permission
  dialog (CLI vs Desktop app). → verify empirically; results below.

### Empirical results (M1)

Verified in this environment:

- **Plugin validation passes** on the installed Claude Code **v2.1.119**
  (`claude plugin validate .` → `✔ Validation passed`).
- **Installed-version discrepancy vs docs** *(resolved 2026-07-19)*: on
  v2.1.119 the validator had **no `--strict` flag** and rejected `$schema` and
  `displayName` as *errors*, so both fields were removed from `plugin.json` for
  compatibility. After upgrading the local CLI to **v2.1.214** (docs list
  `displayName` as requiring v2.1.143+), both fields were re-added
  (`$schema: https://json.schemastore.org/claude-code-plugin-manifest.json`,
  `displayName: "Permission Lens"`) and `claude plugin validate .` passes,
  with and without `--strict`.
- **Exact `hooks.json` invocation works**: piping the full documented
  `PermissionRequest` payload (incl. `permission_suggestions`) through
  `uv run --quiet "${CLAUDE_PLUGIN_ROOT}"/hooks/permission_lens.py` returns
  `{"systemMessage": …}` with **no `decision`/`hookSpecificOutput`** keys — so
  the native dialog will still show. Exit 0.
- **End-to-end latency** (uv warm cache, incl. process startup): ~40–60ms per
  call — far under the 10s hook timeout. In-process Tier 1 analysis is <10ms
  average (tests/test_performance.py).
- **Fail-safe guard verified**: `uv run <bad-path> || true` exits **0**, so a
  broken launcher can never deny a permission (exit 2 would). A launcher error
  goes to stderr (shown as a hook-error notice) with empty stdout → no
  annotation, native dialog shows.

**`systemMessage` rendering — VERIFIED 2026-07-19 (was pending since M1):**

Driven live in Claude Code Desktop with an instrumented hook (a probe wrapper
that logged stdin/stdout of every invocation). Findings:

- **Desktop invokes the hook and receives the `systemMessage`, but does NOT
  render it on the permission dialog.** Proof: a real Desktop `PermissionRequest`
  event (full `session_id`/`cwd`/`permission_mode` payload) logged
  `OUT: {"systemMessage": "ℹ️ Fetches claude.ai"}`, yet the dialog showed no
  annotation. So the plugin is correct end-to-end; the app just doesn't surface
  the field there.
- **The API offers no dialog-text field short of a decision.** The PermissionRequest
  output schema is `hookSpecificOutput.decision.behavior` (allow/deny) +
  `updatedInput`, plus the common `systemMessage`. There is **no** documented
  field to add explanatory text to the dialog *without* deciding — and deciding
  violates the never-gatekeeper core, so it's off the table.
- **CLI**: the standalone terminal `claude` (2.1.215) did **not** fire the plugin
  hook across two fresh sessions in this environment (probe never logged a CLI
  call), despite `claude plugin details` listing the PermissionRequest hook as
  registered. Root cause undetermined remotely; noted, not blocking — even if it
  fired, the Desktop rendering gap is the real blocker for that surface.

**Consequence → M6**: the "annotate the dialog inline via systemMessage" premise
(assumed since M1, never before verified interactively) does **not** hold on the
surfaces tested. The plugin still emits `systemMessage` (lights up if a future
version renders it), and M6 adds an opt-in macOS **notification** channel as the
display that's actually visible today. See the M6 section below.

Still pending (lower priority): `-p` non-interactive behavior (brief says
`PermissionRequest` doesn't fire without a human) — confirm via `--debug`.

**PreToolUse `"ask"` reason rendering — VERIFIED 2026-07-19 (Desktop): IT RENDERS
ON THE DIALOG.** This reopens the inline-annotation premise that the
systemMessage finding above had closed.

Probe: `scripts/probe-pretooluse-ask/` (always returns
`permissionDecision: "ask"` + a marker reason; logs stdin/stdout to
`~/.cache/permission-lens/probe-ask.log`), registered via a scratch project's
`.claude/settings.json` at `~/Code/oss/pl-ask-probe`. Docs basis: hooks §
PreToolUse decision control — for `"allow"`/`"ask"` the reason is "shown to the
user but not Claude"; CHANGELOG 2.1.211 — "a hook `ask` now floors the decision
at a prompt". Findings from a live Desktop session (screenshot-verified,
`permission_mode: "acceptEdits"`):

- **The marker text renders inside the permission dialog body**, between the
  tool description line and the command box. Exactly the surface Permission
  Lens needs.
- **`\n` collapses** — both marker lines flowed as one wrapped paragraph, so
  annotations must be written as a single flowing line (separator like ` · `),
  not relying on newlines.
- **No origin label seen** (`[Project]`/`[Local]`) on this dialog, despite the
  docs mentioning one.
- **Buttons were Deny / "Allow once" only** — no "always allow" /
  permission-suggestion options. Unconfirmed whether hook-`ask` suppresses
  those or this dialog just wouldn't have offered them; compare against a
  no-probe prompt before concluding.
- Payload note: the PreToolUse event carries `tool_use_id`, `prompt_id`,
  `effort`, plus the usual `session_id`/`cwd`/`permission_mode` — richer than
  PermissionRequest's.

Still pending on this probe: (a) the floors-at-a-prompt friction test — allow
`ls` permanently (if offered anywhere), rerun, does the dialog still appear?
(b) same probe in a terminal `claude` session (settings-registered, so also a
data point on the CLI-plugin-hook mystery above).

**Consequence**: migrating the annotation to a PreToolUse hook that returns
`"ask"` + reason only at high severity (`{}` otherwise) would put explanations
on the dialog itself, at the cost of forcing prompts for annotated calls that
rules would have auto-allowed. Severity gating keeps that cost aligned with the
product story ("risky operations always prompt, with an explanation"). Not yet
decided/implemented.

## Design decisions

- **Never a gatekeeper.** No `hookSpecificOutput` is ever emitted. Fail open on any
  internal error: print `{}`, exit 0.
- **Tier 1 parser is deliberately conservative**: a quote-aware scanner that splits
  top-level statements on `;`, `&&`, `||`, `&`, newline, and additionally splits
  pipeline stages on `|`; it flags `$(…)`, backticks, and `<(…)`/`>(…)`, and scans
  substitution bodies as extra statements. It is *not* a bash grammar —
  tree-sitter-bash is a possible later upgrade if false negatives warrant it.
- **Rules are data** (`hooks/rules.yaml`), regex- or predicate-based, bilingual
  (en/zh). Predicates cover the few cases regexes can't express cleanly
  (e.g. `rm -rf` flag/target analysis).
- **PyYAML** is the only non-stdlib dependency (sanctioned by the brief), declared
  via a PEP 723 `# /// script` block and resolved by `uv run` (cached after first
  run; the very first invocation needs network to fetch pyyaml — if that fails the
  hook fails open and the dialog shows unannotated).
- **Reference implementations studied**: `dyad-sh/dyad` `.claude/hooks/`
  (Apache-2.0) — studied for stdin-handling and shell-metacharacter patterns only;
  no code was copied or adapted. Dyad's hooks are PreToolUse *gatekeepers*
  (auto allow/deny), which is exactly what Permission Lens is not.
- **M4 extension point**: `notify(payload)` in `permission_lens.py` is a no-op stub;
  a future `notify_url` config key will POST pending requests to a localhost panel.
  The docs' `http` hook type may be an alternative implementation path.

## M2 (2026-07-19): config + Tier 2 LLM explainer

### Config

- Path: `~/.config/permission-lens/config.json`; schema mirrors
  `config.example.json` in the repo root. Keys: `lang` (`en`|`zh`),
  `min_severity_to_annotate` (`info`|`low`|`medium`|`high`), `max_message_chars`
  (clamped 80–9000, under the 10k hook cap), `llm.*`.
- **Per-key fail open**: a missing/malformed file, or any invalid value, falls
  back to the default for that key only — a broken config can never break the
  hook or (worse) accidentally enable Tier 2 (`enabled` must be literal `true`).
- `min_severity_to_annotate` semantics: `info` (default) annotates everything
  including the neutral ℹ️ summary; `low`+ requires a rule match at/above the
  threshold, otherwise the hook stays silent (prints `{}`).
- Env overrides for tests/debugging: `PERMISSION_LENS_CONFIG` (config path),
  `PERMISSION_LENS_CACHE_DIR` (cache root). The contract tests set both so a
  developer's real config can't leak into subprocess assertions.

### Tier 2 LLM explainer (default OFF)

- **Opt-in only, user's own credentials only**: `llm.enabled: true` plus a
  credential from the user's environment. Resolution order: `$ANTHROPIC_API_KEY`
  (sent as `x-api-key`) then `$ANTHROPIC_AUTH_TOKEN` (OAuth bearer, e.g. from
  `ant auth login` / `ant auth print-credentials --access-token`; sent as
  `Authorization: Bearer` + required `anthropic-beta: oauth-2025-04-20`).
  Both env var names are configurable (`llm.api_key_env` / `llm.auth_token_env`).
  Without a credential, the code path returns before any network import/IO —
  subscription-only users simply keep Tier 1. Note: Claude Code's own login
  credential is NOT touched; there is no supported way to bill Tier 2 to a
  Pro/Max subscription.
- Raw HTTP via stdlib `urllib` (no SDK dependency): `POST
  https://api.anthropic.com/v1/messages`, headers `x-api-key` +
  `anthropic-version: 2023-06-01`, model `claude-haiku-4-5` (alias verified
  against the current model catalog 2026-07-19). `urllib.request` is imported
  lazily inside the fetch so Tier 1 startup cost is unchanged.
- **Privacy invariant** (tested): the request body is exactly
  `{model, max_tokens, system, messages}` where `system` is a static prompt and
  `messages` is the command string alone. No cwd, session id, or transcript
  content ever leaves the machine. Commands >4000 chars skip Tier 2 entirely.
- **3s hard timeout**: `urllib`'s `timeout` is per socket operation, so the
  fetch runs in a daemon thread with `join(timeout_seconds)` — a true wall-clock
  cap (verified by test: a 1.5s-slow fake API is abandoned in <1s at a 0.2s
  deadline). On expiry the thread is abandoned and Tier 1 output ships alone.
- **Cache**: `~/.cache/permission-lens/llm/<sha256(model\nlang\ncommand)>.json`
  holding `{"text", "created"}`; TTL `llm.cache_ttl_days` (default 7, `0`
  disables caching). Writes are `os.replace`-atomic; corrupt/expired entries
  are treated as misses. Cache is best-effort — failures never surface.
- **Silent degradation everywhere**: disabled / no key / network error /
  non-JSON response / empty text / timeout all return `None`; the dialog then
  shows the pure Tier 1 message. Process-level contract tests cover
  `llm.enabled` with no key and a syntactically broken config file.
- Message layout: the model line is appended last with a 🤖 prefix, so
  truncation at `max_message_chars` always keeps the deterministic Tier 1
  content first.
- `lang: "zh"` now also localizes the neutral ℹ️ summaries (M1 had rule
  explanations bilingual but summaries EN-only) and the Tier 2 system prompt.
- Suite: 160 tests (was 123); Tier 2 tests are fully offline via monkeypatched
  `urllib.request.urlopen`. The no-network guards *record* calls and assert the
  list stays empty — a raised exception alone would be swallowed by the
  deadline worker and the tests would pass vacuously.
- Independent pre-commit review (2026-07-19) found no invariant violations;
  fixes applied from it: vacuous no-network tests (above), `cache_ttl_days: 0`
  now disables writes as well as reads, NaN/Infinity config values fall back to
  defaults instead of clamping to MAX, the Tier 2 opt-in gate tolerates
  unvalidated configs, `_log_debug` honors `PERMISSION_LENS_CACHE_DIR`, and the
  timeout ceiling dropped 8s→6s (the 10s hook timeout also covers uv/python
  startup, not just the API call).

## M3 (2026-07-19): packaging polish

- **README** rewritten as a full bilingual (EN + 中文) doc: what/why, the
  two-tier design table, three install routes, the config-key table, the
  "Tier 2 uses your own account" credential section (API key + OAuth token),
  a "testing it locally" section, and the design principles. Anchor-linked
  language switcher at the top of each half.
- **Marketplace**: repo is its own single-plugin marketplace at
  `.claude-plugin/marketplace.json` (self-hosting pattern, `source: "./"`).
  `--strict` requires a marketplace description, supplied under `metadata`.
  Verified: `claude plugin validate . --strict` passes for BOTH the plugin
  manifest and the marketplace manifest on v2.1.214. Marketplace install
  (`/plugin marketplace add … && /plugin install permission-lens@permission-lens`)
  only works once the repo is pushed to a git host — there is no remote yet,
  so local dev uses `--plugin-dir` / the manual settings.json block.
- **CI-able check script**: `scripts/check.sh` runs pytest, a real-`uv-run`
  hook smoke test (asserts exit 0, a `systemMessage`, and NO decision field),
  and `claude plugin validate . --strict` (skipped with a note if the CLI is
  absent, so CI without `claude` still passes the rest). `set -euo pipefail`;
  the smoke test captures via `if ! out=$(...)` so a non-zero hook exit is
  reported rather than silently aborting under `set -e`.

## M5 (2026-07-19): multi-tool coverage (WebFetch / Write / Edit)

- **Motivation**: a real Desktop test hit a `WebFetch` permission dialog with no
  annotation — correct then (matcher was Bash-only) but a genuine gap.
- **Matcher**: `hooks.json` → `"Bash|WebFetch|Write|Edit"` (explicit list, not
  `"*"` — only spawn uv for tools we can explain).
- **Field verification**: per-tool `tool_input` fields were verified empirically
  from real session transcripts (see "Confirmed facts" item 1), since the hooks
  reference documents only the Bash shape. WebFetch=`{url,prompt}`,
  Write=`{file_path,content}`, Edit=`{file_path,old_string,new_string,replace_all}`.
  MultiEdit unverified → deliberately not covered.
- **Design — tool dispatch, shared rendering**: `TOOL_ANALYZERS` maps tool name
  → analyzer; each returns `(matches, neutral_summary, tier2_subject, kind,
  notify_subject)` or None. Unknown tool → None (native dialog, no annotation).
  The rule-result shape, severity sort, threshold filter, and renderer are
  unchanged and shared across tools; only matching + neutral summary differ.
  `format_message(parsed, …)` kept as a Bash wrapper over the new generic
  `render_message(matches, neutral, …)` so the M1–M2 Bash tests are untouched.
- **Rules are still data**: new `hooks/rules_web.yaml` (5 URL rules) and
  `hooks/rules_path.yaml` (11 path/content rules) reuse the same rule schema.
  A generic `match_string_rules(rules, {field: subject})` matches each rule's
  regex against the subject named by its `field` (`url` / `path` / `content`);
  the loader assigns a per-file default field (`url` for web, `path` for path
  rules). *Bug caught in smoke test*: web rules initially defaulted to field
  `path` and matched nothing — fixed via `default_field`. Path regexes use
  `(^|/)` anchors so `~/.ssh/x` and `/Users/x/.ssh/x` both match; the analyzer
  `expanduser`s the path first.
- **Tier 2 privacy extended**: per-tool system prompts (`bash`/`url`/`path`);
  the subject sent is the command / URL / path only. WebFetch never sends the
  `prompt`; Write/Edit never send file **content** unless the new
  `llm.send_file_content` (default false, literal-true to enable) is set. Cache
  key now includes `kind` so a URL and an equal-string command can't collide.
  Tests assert the secret/prompt never appears in the request body by default.
- Suite: 204 tests (was 160); +`tests/test_multitool.py`, fully offline, with
  per-rule coverage assertions (every web/path rule needs a positive case).

### Desktop `uv`-not-on-PATH fix (2026-07-19)

- **Symptom** (hit live): a **Bash** permission dialog in Claude Code Desktop
  showed no annotation. Root cause proven, not guessed: macOS GUI apps launch
  with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, which excludes Homebrew's
  `/opt/homebrew/bin` where `uv` lives. `uv run … || true` then hits
  `uv: command not found`, exits 0 (fail open), emits nothing → prompt shows
  unannotated. Terminal `claude` (full shell PATH) was unaffected — the clean
  discriminator.
- **Fix**: the `hooks.json` command is now
  `sh -c 'command -v uv >/dev/null 2>&1 || PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; uv run --quiet "${CLAUDE_PLUGIN_ROOT}"/hooks/permission_lens.py' || true`.
  If `uv` is already on PATH (terminal) nothing changes; otherwise common install
  dirs (uv-standalone `~/.local/bin`, cargo `~/.cargo/bin`, Homebrew AS/Intel)
  are prepended before the run. Verified in three scenarios: GUI-minimal PATH now
  annotates; `uv` genuinely absent still fails open (error to stderr, exit 0, no
  stdout); normal terminal unchanged. README's manual `settings.json` block and
  `scripts/manual-test.md` updated to carry the same prefix + document the gotcha.

## M6 (2026-07-19): desktop notification channel

- **Why**: the `systemMessage`-not-rendered finding above means the inline
  annotation is invisible on the surfaces tested. A notification is the pragmatic
  channel that's actually visible today; the dialog stays native.
- **Config** `notify.{enabled,min_severity}` — **opt-in** (`enabled` default
  false, literal-true to enable, consistent with Tier 2), `min_severity` default
  `high` so only genuinely dangerous prompts interrupt. Validated per-key like
  the rest.
- **Mechanism**: `send_desktop_notification(title, body)` runs `osascript -e
  'display notification …'`; **macOS only** (`sys.platform == "darwin"`, else
  no-op), `subprocess` imported lazily, 3s timeout, stdout/stderr to DEVNULL.
  `_osa_escape` escapes `\` / `"` / newlines for the AppleScript string (title +
  body are our own rule text — no user input, no command/URL/path in the
  notification — so no injection surface).
- **Invariants preserved**: `maybe_notify` is a best-effort SIDE EFFECT wrapped
  in try/except; it fires only when enabled + there are matches + top severity ≥
  threshold, and it runs *after* `passes_threshold`. It never touches stdout and
  a failure never propagates — `systemMessage` is still emitted and exit stays 0
  (tested: a notifier that raises leaves `build_message` returning the normal
  message). The returned message is byte-identical whether notify is on or off.
- Verified live on this Mac: real notifications fired for a HIGH Bash pipe-to-shell
  and a credentials-in-URL WebFetch; `ls` (info) stayed silent under
  `min_severity: high`; all three exit 0 and still return `systemMessage`.
- Suite: 219 tests (was 204); +`tests/test_notify.py`, fully offline
  (`send_desktop_notification` / `subprocess.run` monkeypatched, platform guard
  tested both ways). Plugin version 0.4.0.

## M7 (2026-07-19): migration to PreToolUse "ask" — the explanation reaches the dialog

- **Why**: the PreToolUse probe (§ above) proved `permissionDecision: "ask"` +
  `permissionDecisionReason` renders ON the Desktop permission dialog — the
  surface the whole product wanted since M1 and that PermissionRequest's
  `systemMessage` could not reach. The plugin now uses it.
- **New contract** (`hooks.json` event: PermissionRequest → PreToolUse):
  - Rule match at/above `ask.min_severity` (new config, default `high`;
    accepts `low|medium|high`, rejects `info` — it would prompt on every call)
    → `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
    "permissionDecision": "ask", "permissionDecisionReason": <one line>}}`.
  - Everything else → `{}`. No `systemMessage` anywhere anymore: on PreToolUse
    it could render per-call noise in transcripts, and the reason is the
    channel now.
  - Never-gatekeeper restated for the new event: the ONLY decision ever
    emitted is `"ask"` — never allow/deny. "Ask" floors the decision at a
    prompt (CHANGELOG 2.1.211): a flagged-but-allowlisted call now prompts.
    Default `high` keeps that friction ~zero (🔴 commands are essentially
    never allowlisted); `medium` is the user's explicit opt-in (owner decision
    2026-07-19: 🟡 as a config option, not default).
  - Fail-open unchanged, but exit 2 now means BLOCK (not deny) — same
    conclusion: `{}` + exit 0 on every failure path.
- **Single-line reasons**: the probe showed the dialog collapses `\n`, so
  `render_reason` (replaces `format_message`/`render_message`) emits one line:
  `{emoji} {label} · {risk sentence}` + ≤2 extra `{emoji} {explanation}` parts
  + optional `🤖 {tier2}`; every part passed through `_one_line`.
- **Copy pass** (owner request: natural language, nothing to look up): every
  `risk_*` in rules.yaml / rules_web.yaml / rules_path.yaml rewritten as one
  self-contained plain sentence (what it does + concrete consequence, no
  shell jargon), both languages; `explanation_*` now a jargon-free short
  phrase (used by notifications and the extras). Regexes/ids/severities
  untouched — the analyzer and corpus tests are unaffected.
- **Notification channel repositioned**: `maybe_notify` now runs BEFORE the
  ask gate (independent thresholds). On PreToolUse it fires pre-permission,
  so it can flag calls that auto-run with no dialog — documented in README as
  a "this just happened" heads-up. `min_severity_to_annotate` is gone
  (annotation now only exists when asking); old configs carrying it just get
  the key ignored by per-key validation.
- **Removed**: `format_message`, `render_message`, `RISK_LABEL`, the ℹ️
  neutral-summary output path (neutral summaries survive for info-level
  notifications only).
- Suite: 225 tests (was 219) — output contract rewritten around ask/{} (incl.
  "only ever ask", "no systemMessage", medium-silent-by-default,
  medium-asks-when-configured), ask-threshold gate tests, single-line
  assertions; `check.sh` smoke test now asserts ask-for-dangerous and
  `{}`-for-benign. Plugin version 0.5.0.
- Still pending from the probe: (a) whether hook-`ask` suppresses the
  "always allow" options (dialog showed only Deny / Allow once — needs a
  no-probe comparison); (b) CLI rendering of the reason; (c) the M4 panel
  decision — deprioritized now that high-risk explanations are on the dialog.

## M8 (2026-07-19): heartbeat — "checked and clean" vs "hook never ran"

- **Why** (owner request): with M7, a benign call leaves the dialog bare by
  design — indistinguishable from a dead hook. The owner first asked for a 💚
  badge on benign dialogs; that is structurally impossible without gatekeeping
  (dialog text only rides on "ask", "ask" floors at a prompt, and PreToolUse
  cannot know whether a prompt would have happened anyway — the rejected
  "info"-threshold in another costume). Heartbeat solves the underlying need
  off-dialog.
- **Mechanism**: `record_heartbeat(tool, matches, asked)` runs on every
  analyzed invocation (after the notify side effect, before the ask gate
  returns) and atomically rewrites `<cache>/heartbeat.json`: last {ts, tool,
  severity, asked} + per-day counters {total, high, medium, low, none, asked},
  reset on date change. tmp + os.replace like the LLM cache — a concurrent
  hook can lose a count, never corrupt the file. Privacy: NEVER stores
  commands/URLs/paths.
- **Invariants preserved**: best-effort side effect wrapped in try/except
  (tested: os.replace raising leaves build_message returning the normal
  reason); stdout/exit untouched; corrupt heartbeat file is replaced, not
  fatal.
- **Reader**: `scripts/lens-status.py` (stdlib, plain python3) prints version,
  last-check age/tool/outcome, and today's counters; honors
  PERMISSION_LENS_CACHE_DIR / PERMISSION_LENS_CONFIG, bilingual via config
  lang.
- **Tests**: conftest gained an autouse `_hermetic_cache` fixture (all
  in-process cache writes go to tmp — heartbeat made the pre-existing gap
  matter). Suite: 232 tests (+7 in test_heartbeat.py). Plugin version 0.6.0.

## M9 (2026-07-19): session name in notifications

- **Why** (owner request): M6's known weakness was that notifications from
  several concurrent sessions can't be told apart. The PreToolUse payload
  carries `transcript_path`, and the transcript itself records the session
  title — so the pairing problem is solvable after all.
- **Verified 2026-07-19** against a real transcript: titles are appended as
  their own JSONL lines, `{"type":"custom-title","customTitle":…}` (user-set)
  and `{"type":"ai-title","aiTitle":…}` (auto-generated), both keyed by
  sessionId. No title field exists on the hook payload itself.
- **`session_label(event)`**: scans the transcript for the latest title of each
  kind, prefers `custom-title` (user intent beats generated), flattens/caps at
  60 chars; falls back to `basename(cwd)`, then None. Reads at most the last
  4MB and pre-filters lines on `-title"` before parsing JSON. An unreadable
  transcript falls back to the folder rather than losing the label (its own
  try/except — a bug caught in testing).
- **Cost containment**: called only *inside* `maybe_notify`, past the enabled +
  threshold gates, so a below-threshold call pays nothing (tested). The
  notification path already pays for an osascript subprocess, so the file scan
  is not on the hot path.
- **Composition changed**: title `{emoji} {LABEL} · {session}`, body
  `{tool} · {explanation}`. Session identity moved to the title because "which
  window is asking?" is the first question a notification must answer.
- **Injection surface**: session titles are user/model-generated text now
  interpolated into AppleScript — `_osa_escape` (existing, tested) escapes
  backslash/quote and flattens newlines.
- Suite: 241 tests (+9). Plugin version 0.7.0.

## M10 (2026-07-19): locale files — adding a language is one file, no code

- **Why** (owner request: "怎么支持更多的语言"): text was scattered across 10
  places — 52 rules × 4 text fields in 3 rule YAMLs, plus 9 language dicts in
  permission_lens.py and lens-status.py, plus a hardcoded `_LANGS`. Adding a
  language meant touching all of them, and every NEW rule needed copy in every
  language inline. The blocker was structure, not translation.
- **Structure**: `hooks/locales/<lang>.yaml` with sections `rules` (keyed by
  rule id), `ui`, `verbs`, `llm_prompts`, `status`. `rules*.yaml` now hold
  matching logic only. `en` is the base; `load_locale(lang)` deep-merges the
  requested locale over it, and a **blank** string does not override (so an
  untranslated placeholder falls back rather than rendering empty).
  `available_langs()` discovers files on disk and always includes `en`, so a
  broken install still validates `lang: "en"`.
- **Extraction was mechanical, not retyped**: a one-off script read the rule
  YAMLs and the live module dicts to emit en/zh, then stripped the text fields
  from the rule files line-by-line (preserving their comments). No copy was
  re-keyed by hand.
- **lens-status.py** now imports the hook module for config + locale instead of
  carrying its own copies; it declares pyyaml via PEP 723, so it runs as
  `uv run scripts/lens-status.py` (was bare python3).
- **Guard rails** (`tests/test_locales.py`, 16 tests): every rule id has
  English text; no locale references a nonexistent rule; each shipped locale
  renders a complete single-line reason; unknown language and missing locale
  dir degrade to the base; missing/blank keys fall back per key. This is what
  keeps "add a rule, forget the copy" from shipping an empty headline.
- **Languages seeded** (owner's pick): ja, es, zh-Hant, fr — translated by one
  subagent each against the copy contract, marked machine-translated in their
  headers pending native review.
- Suite: 257 tests before the new locales. Plugin version 0.8.0.

## M11 (2026-07-19): concrete detail + opt-in task context

Owner's observation: the dialog said a script would be downloaded but not from
where or to what effect, and a rule-level warning fires identically whether or
not the operation matches the task at hand. Two fixes, deliberately at
different cost tiers.

- **A. Detail extraction (offline, free)**: rules opt in via `detail:
  <extractor>` in rules*.yaml; `extract_detail` pulls the concrete fact out of
  the subject and `render_reason` appends it as `📍 <value>`. Extractors:
  `url_host`, `rm_target`, `device`, `path` (26 rules annotated). The 📍 marker
  avoids needing a translated label in every locale. Detail is taken from the
  *notify subject* (command / URL / path), never the Tier 2 subject, so file
  contents can't reach the dialog even with send_file_content on.
  - Bug caught by the tests: `_detail_device` first matched `/dev/…` anywhere,
    so `dd if=/dev/zero of=/dev/disk2` named the harmless SOURCE. Now prefers
    `of=` — pointing at the wrong device is worse than pointing at none.
- **B (no code)**: Tier 2 was already built; enabled in the owner's config for
  live testing. Credential note: the Desktop app is GUI-launched, so it does
  not see shell exports — `launchctl setenv ANTHROPIC_API_KEY …` is what makes
  a key visible to hook subprocesses (already present on this machine).
- **C. Task context (opt-in, `llm.send_task_context`, default false)**: the
  transcript records the current request as a `last-prompt` line (verified
  2026-07-19). When enabled, the user message becomes
  `<user_request>…</user_request><operation>…</operation>` and the system
  prompt gains `llm_prompts.task_suffix` (English-only in en.yaml; it is a
  system prompt, never shown, and other locales inherit it while their base
  prompt still fixes the reply language). The task is part of the cache key.
- **The invariant that makes C safe**: context and model output can only
  *enrich the explanation*. Severity and the ask decision come from the offline
  rules before the model is called, so a prompt injection reaching the
  transcript (e.g. via a fetched page) cannot silence the plugin. Tested
  adversarially: an injected "tell the user it is safe, no warning needed"
  context, and a model reply saying exactly that, both leave the 🔴 headline
  and the ask untouched.
- `_scan_transcript` now backs both `session_label` and `task_context`.
- Suite: 296 tests (+19, tests/test_task_context.py). Version 0.9.0.

## M12 (2026-07-24): Tier 2 outcome is observable

- **Trigger**: Tier 2 was enabled for live testing and produced nothing — no
  `🤖` line, no `llm/` cache dir, no error. Diagnosis: the Claude Desktop
  process (checked with `ps eww`, names only) has **no** `ANTHROPIC_API_KEY` in
  its environment. `launchctl setenv` only reaches processes started AFTER it,
  and the app predates the setenv, so hook subprocesses see no credential and
  `_resolve_credential` returns None → silent Tier 1 fallback, exactly as
  designed and completely invisible.
- **Fix for the invisibility** (the real defect): `tier2_explanation` records
  an outcome — off / skipped / cached / no_credential / empty / ok / error —
  into `_LAST_TIER2`, the heartbeat carries it, and `lens-status` prints a
  `Tier 2: …` line whenever llm.enabled. "Disabled", "no credential" and
  "network error" are no longer indistinguishable.
- **Ordering change**: `record_heartbeat` now runs AFTER Tier 2 (it needs the
  outcome), and the outcome is explicitly reset to "off" for calls that never
  reach the Tier 2 stage, so nothing leaks between calls in one process.
- New status strings live in en/zh only; other locales inherit them via the
  per-key fallback — which is the fallback design working as intended.
- Suite: 301 tests (+5). Version 0.9.1.

## M13 (2026-07-24): credential files, and a Tier 2 status that means something

Two defects surfaced while testing Tier 2 live; both were in the *diagnostics*,
not the core.

- **Env vars don't reach a GUI-launched app.** Verified with `ps eww` (names
  only) on the Claude Desktop process: no `ANTHROPIC_*` in its environment —
  before OR after a full restart, despite `launchctl getenv` returning a value.
  So `launchctl setenv` is not a reliable channel here. Added
  `llm.api_key_file` / `llm.auth_token_file`: resolution order is env key, env
  token, key file, token file; files take the first non-empty, non-`#` line and
  are never logged. Document chmod 600.
- **The Tier 2 status line was meaningless.** It was folded into `last`, which
  every benign call overwrites — and benign calls never reach Tier 2, so it
  read "off" almost always. Now stored as its own `tier2: {outcome, ts}` block,
  refreshed ONLY by calls that reached the Tier 2 stage, and printed with an
  age. New `tier2_never` state for "no risky call has reached it yet".
  Regression test: a benign call must leave the block untouched.
- Suite: 305 tests (+4). Version 0.10.0.
