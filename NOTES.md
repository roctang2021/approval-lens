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

## M14 (2026-07-25): who the reader should believe

Three owner findings from live use, all traceable to one root cause: Tier 1 and
Tier 2 were both answering "how dangerous is this?".

- **Two verdicts on one dialog.** Tier 2 wrote "风险不大" beside Tier 1's
  🔴 高危 on the same line. The reader had no way to pick. Root cause was the
  prompt: it asked for "what it does and any notable risk", which is the rules'
  job. Rewrote all six locales' llm_prompts: the model is told a rule engine
  has ALREADY rated the risk, must not repeat or re-rate it, and must never
  say safe/unsafe or advise approving. Its job is the part the rules cannot
  know — what THIS instance concretely does (which host, which file, which
  flags). Reader now gets evidence next to the verdict instead of a competing
  verdict, and the fallible layer stays clearly subordinate.
  - Why not let the model adjust severity: context and command text are
    attacker-reachable, so a model that can lower severity is a model that can
    be talked into silence. Tested adversarially since M11.
- **The rule was wrong, and the model was right.** `macos-keychain-dump`
  lumped `dump-keychain` (empties the whole keychain) together with
  `find-generic-password -s X` (returns metadata for one named item). Split by
  whether the secret is actually printed: `dump-keychain` and lookups carrying
  `-w`/`-g` stay high; a plain lookup is now `macos-keychain-lookup` at medium
  — so it no longer forces a dialog at the default gate. A persistent
  rule/model mismatch is a rule bug; this is the first one it caught.
- **The dialog line had no hierarchy** and leaked internal markers: 📍 and 🤖
  were unexplained emoji standing in for "target" and "model-written". New
  layout, owner-picked: `{severity} · {target} · {why this class is risky}`
  plus `· AI: {facts}` when Tier 2 is on. Severity leads (decides whether to
  keep reading), the extracted target comes second (most decision-relevant
  fact, lands where the eye goes), model text is last behind an explicit,
  localized `AI:` prefix — the reader must be able to tell generated text from
  audited copy. `ai_label` carries its own punctuation per locale
  (en "AI: ", zh "AI：", fr "IA : ").
- Suite: 315 tests (+8): prompts must keep the no-rating clauses, every locale
  must ship an `ai_label`, layout assertions moved from emoji markers to
  positional parts. Version 0.11.0.

### M14 follow-up: the AI segment reads as an aside, not a debug tag

Owner review of the shipped layout: a bare `AI:` joined by ` · ` was too blunt
— a mechanism label presented as a peer of the rule copy. Dropping the marker
entirely was rejected: this plugin's whole posture is that its fallible parts
are visible (the model demonstrably got a wrapped `echo …` wrong), so hiding
which half is generated would be off-brand.

Fix is typographic demotion plus softer wording, not removal:
- `ui.ai_wrap` is now a full template owning label, brackets and spacing —
  en `" (AI note: {})"`, zh `"（AI 解读：{}）"`, fr `" (Note IA : {})"`. A
  missing `{}` falls back rather than silently swallowing the model sentence
  (tested).
- Brackets rather than a dash: the rule copy already uses em dashes heavily
  ("立刻运行——你看不到代码内容"), so a ` — ` separator collided with them. A
  first attempt at a dash was replaced for exactly that reason.
- Version 0.11.1, 316 tests.

## M15 (2026-07-25): naming a dangerous pattern is not running it

Owner asked the sharpest possible question about a live dialog — "should the
user click Allow or Deny?" — and the honest answer was **Allow**: the command
was `echo "curl … | bash "`, which prints a string. Every layer on that dialog
was wrong (🔴, the target, the rule sentence, and the cached AI note).

- **Root cause**: `scope: whole` rules regex the RAW command text, discarding
  what the parser already knows. `Parsed('echo "curl … | bash "')` yields a
  single `echo` stage — the quote-aware splitter never saw a pipe. The rules
  threw that away and matched the text inside the quotes.
- **Not a test artifact.** `git commit -m "fix the curl | bash install path"`
  — an ordinary everyday command — fired 🔴 HIGH. This is the cry-wolf failure
  mode that teaches users to ignore the tool.
- **The fix direction already existed in the codebase**: `rm-rf-*` are
  predicates over the parsed structure, which is exactly why
  `grep -n "rm -rf /" deploy.sh` never false-fired. The regex rules simply
  never got the same treatment.
- **`verb:` guard** (new optional rule field, 30 rules annotated): the rule can
  only fire when some stage actually runs that program. `_command_names()`
  returns a stage's own verb — so `mkfs` in `echo mkfs` is an argument, not an
  invocation — and falls back to scanning every token when the stage starts
  with a wrapper (`sudo` / `env` / `nice` / `nohup` / `timeout` / …), whose own
  name would otherwise hide the real verb. Quote safety is free: a quoted run
  of words survives shlex as one token, so an anchored fullmatch can never see
  the `curl` inside it. Patterns are written unanchored in YAML and anchored by
  `fullmatch`, so a rule author cannot leak a substring match (tested).
- **Not guarded** (no single program to anchor on — path/redirect shaped):
  ssh-key-access, aws-creds-access, dotenv-access, shell-history-access,
  shell-rc-append. `echo "~/.ssh/id_rsa"` can still false-fire; these want
  predicates over the parsed redirect/argument structure, left as follow-up.
- **Gap noticed, not closed**: plain-text obfuscation — `echo "<command>" | bash`
  — has no rule. base64 and hex variants are covered; the plaintext one isn't.
  Separate rule, deliberately not folded into this change.
- Suite: 346 tests (+30): 7 quoted-mention entries in the benign corpus, plus
  invocation/wrapper/anchoring tests. Version 0.12.0.

## M16 (2026-07-25): a heredoc payload is data, not shell

Same disease as M15, different carrier: M15 was text hidden inside quotes,
this is text hidden after a newline.

- **Symptom**, spotted by the owner on a live dialog: a release command reading
  `cat >> NOTES.md <<'EOF' … EOF` produced "🔴 高危 · /dev/disk2 · 这会格式化
  一个存储设备". Nothing was being formatted — the payload was prose.
- **Root cause**: statements split on newlines, so every line of a heredoc was
  parsed as its own command. A documentation line beginning `mkfs.ext4
  /dev/disk2 …` became stage name `mkfs.ext4`, passed the new verb guard
  (it IS in command position, for a statement that was never a statement), and
  the `device` extractor pulled `/dev/disk2` out of the same prose. Writing
  release notes *about* dangerous commands set off 🔴 every time — the plugin
  false-alarmed on the very commit fixing its previous false alarm.
- **Fix**: `Parsed.code` is the command with data heredoc payloads removed;
  every rule now matches `code` rather than the verbatim `command` (which is
  kept for anything needing the original text).
- **The exception that keeps it honest**: `bash <<EOF` / `sh <<EOF` EXECUTE
  their body, so those payloads stay analyzed. Dropping them would trade a
  false positive for a false negative, which is the wrong direction for a
  security tool. Tested both ways.
- Unterminated heredoc → everything after the opener is treated as payload.
- Suite: 351 tests (+5). Version 0.13.0.

## M17 (2026-07-25): the checklist could not see its own blind spots

Owner ran section 1 (`rm -rf $HOME/projects`) and got no dialog. Not a miss:
Claude inspected the target first, found it absent, and declined to run
`rm -rf` at all — so the command was never issued as a tool call and the
PreToolUse hook never fired. The heartbeat proved it (high/asked unchanged at
29/29), and feeding the hook directly rendered the rule correctly, target
extraction and all.

Two things this exposed, both in the tooling around the plugin rather than in
the plugin:

- **High-severity cases can't be verified by asking a model to run them.**
  Refusing a destructive command is correct behavior, but it makes "no dialog"
  ambiguous. Added `scripts/preview.sh` — feeds an operation straight to the
  hook and prints the dialog text, executing nothing, with its own cache dir so
  it never disturbs the heartbeat. Section 1 of the checklist now leads with
  how to tell "model declined" from "plugin missed".
- **`lens-status` reported the checkout's version, not the running one.** The
  installed plugin lives in a versioned copy and only changes on
  `plugin update` + app restart, so a repo that is ahead behaves like the older
  build — which is exactly what was happening (0.13.0 published, Desktop still
  running 0.12.0, heredoc fix not live). The heartbeat now records the running
  build and lens-status flags a mismatch outright.
- Also confirmed live: known gap #1 is real —
  `scripts/preview.sh --write '/Users/x/.ssh/config'` fires ssh-key-access at
  medium purely from the quoted path in the argument. Silent at the default
  gate; still wants a predicate.
- Suite: 352 tests. Version 0.14.0.

## M18 (2026-08-14): section 4, and a rule whose premise was false

Owner ran the non-Bash cases. WebFetch and Write both render correctly
end-to-end (`user:pass@…` → 🔴 with host + AI note; content carrying
`curl x | sh` → 🔴 content-remote-exec). Three findings beyond that:

- **`web-insecure-http` warned about a risk that cannot happen — removed.**
  Its copy said http:// is transmitted in the clear and can be read or altered
  in transit. But the WebFetch tool upgrades HTTP to HTTPS before the request
  leaves, so the interception it described is impossible for the only tool the
  rule applies to. A security tool asserting an impossible risk spends the
  reader's trust for nothing. Removed from rules, all six locales, corpus and
  fixtures. (`curl http://…` in Bash *is* plaintext — a different rule against
  a different tool, noted as follow-up rather than smuggled in here.)
- **Three interception layers, only one is ours.** Measured: `curl … | bash`
  and `user:pass@…` reached our dialog; `?api_key=sk-123` was denied silently
  by Claude Code's own auto-mode classifier ("Blocked by classifier", no rule
  named, no dialog); `127.0.0.1:8080/admin` hit nothing at all and went
  straight to the network. So our copy is only visible on the paths that
  actually reach a permission prompt — worth stating rather than assuming.
- **The checklist told people to write to REAL security files.** Third time
  the same flaw ("harmless even if allowed") got past me, after sections 1 and
  3. Section 4 now uses path-shaped stand-ins under /tmp/pl-check — the rules
  match path SHAPE (`.ssh/`, `sudoers`, `.git/hooks/`), so a stand-in produces
  the identical dialog while touching nothing live. Verified each keeps the
  same rule at the same severity. Also warns against combining "write
  curl|sh" with "write into pre-commit", which installs a hook that fetches
  and runs code on every commit, with no dialog from then on.
- Suite: 352 tests. Version 0.15.0.

## M19 (2026-08-14): section 2, and dry-run false alarms

Flipped `ask.min_severity` to medium so the owner could exercise the 25
medium/low rules. Rewriting section 2 for safety turned up one more instance of
the M18 defect class:

- **Section 2 was 24/25 real destructive commands** — `git push --force origin
  main`, `git clean -fdx`, `crontab <file>` (which REPLACES the entire existing
  crontab, it does not append), `sudo rm /etc/hosts`. Fourth section to need
  this fix. All 25 now use stand-ins verified to hit the same rule at the same
  severity: relative paths for rm, `/tmp/pl-check/` shapes for the credential
  readers, non-existent remotes/users/services/buckets for the rest, and
  `git -C /tmp/pl-check/norepo` for the three git cases — which is safe only
  because the directory does not exist, so the checklist says not to create it.
- **`npm publish --dry-run` and `aws s3 rm --dryrun` fire at full severity.**
  The dialog then says "publishes to npm, effectively cannot be taken back" for
  a command that uploads nothing. Same shape as the web-insecure-http removal:
  copy asserting a consequence the command cannot have. Not fixed here (it
  needs a flag-aware exception in both rules, and changing rules mid-test would
  invalidate the run the owner is about to do); the checklist uses stand-ins
  that really do reach the network instead. TODO next round.
- Note `_target_is_risky` treats ANY absolute path as risky, so
  `rm -rf /tmp/x` is high while `rm -rf ./build/x` is medium. Deliberate
  (documented at the predicate), but it means a /tmp stand-in cannot be used to
  exercise the medium rm rule — the checklist uses a relative path.

## M20 (2026-08-14): 25 live cases, and what Tier 2 got wrong

Owner ran all 25 section-2 cases against a real Desktop session at
`min_severity: medium`. **Tier 1: 25/25 as predicted** — 23 dialogs, and the two
🟢 low cases (#9 `.env`, #19 `git remote set-url`) correctly stayed silent
below the gate. The rendered copy matched the generated checklist verbatim,
which is what generating it from the hook rather than by hand was for.

Tier 2 is the interesting half. Scored by hand across 25:

- **Two factual errors, both inventing flag semantics.** #2 said `shred -u`
  "controls how many times it overwrites" (it deallocates and removes the file;
  `-n` sets the count). #14 said `sudo -n` means "runs without needing a
  password" (it means fail rather than prompt — the opposite reassurance).
  Both are stated with full confidence. A dialog that teaches the reader a
  false fact about a flag is worse than one that says nothing.
- **Root cause was our own prompt.** It asked the model to name "which flags
  change what happens" — an explicit invitation to write a flag glossary from
  memory. Changed in all six locales to ask for the VALUE an argument sets
  (755, 777, the search term — all of which it got right), to state plainly
  when a target evidently does not exist, and not to explain an individual
  flag unless certain.
- **Where Tier 2 genuinely earned its place**, and Tier 1 structurally cannot:
  - *Predicting failure*: #15, #16, #21, #23, #25 each said outright that the
    user/remote/file does not exist so the command will fail.
  - *Correcting Tier 1's over-claim on this instance*: #6 Tier 1 says the data
    "leaves this machine"; Tier 2 pointed out the destination is 127.0.0.1.
    #20 Tier 1 says "published to the whole world"; Tier 2 pointed out the
    registry is a local private one. The rules describe a CATEGORY, so on any
    given instance they can overstate — this is the same defect class as the
    removed web-insecure-http rule, except here Tier 2 catches it live.
  - *Resolving the dynamic case*: #13 `eval "$(echo true)"` — explained that
    this particular expansion is just `true`, while the pattern stays risky.
- **Inconsistent about the failure prediction**: #17, #18, #22, #24 face the
  same "target does not exist" fact and never mention it, while #15/#16/#23 do.
  The prompt change targets this directly.
- **Four near-pure restatements** (#1, #7, #8, #11) that add nothing over
  Tier 1. #11 is the sharpest miss: `secret-tool` does not exist on macOS at
  all, which is the one fact worth having.

Version 0.16.0.

## M21 (2026-08-14): the prompt was not part of the cache key

Reran cases 2, 14, 17 and 22 after the M20 prompt rewrite. All four AI notes
came back **byte-identical** — `shred -u` still described as controlling the
overwrite count, `sudo -n` still as "runs without needing a password". The
prompt change had not failed; the model was never called.

`_llm_cache_path` keyed on `model + lang + kind + task + subject`. The system
prompt was absent, so editing a prompt invalidated nothing: every command seen
before kept serving the answer the OLD prompt produced, for the full 7-day TTL.
The prompt was therefore untestable on exactly the cases that motivated
changing it — you could only observe the new wording on a command you had never
run, which is the opposite of how anyone verifies a fix.

Fixed by folding the assembled system prompt (including the task suffix, when
task context is on) into the digest, with two tests: one asserting a changed
prompt yields a different path, one asserting stability when nothing changed.
Old entries are simply never looked up again.

This is the third time the same shape of bug has cost real time: something the
tool reports looked current but was not — the repo-vs-running version (M17),
the heartbeat counters (open), and now the Tier 2 cache. A cached or stale
value presented without saying it is cached is worse than no value.

Version 0.17.0. 354 tests.

## M21b (2026-08-14): "installed" and "running" are different questions

The M21 cache fix appeared not to work either — the same four cases came back
byte-identical a second time. Cause: `claude plugin update` writes each build
to its own version-named directory under
`~/.claude/plugins/cache/<marketplace>/permission-lens/<version>/`, and three
versions were sitting there at once (0.15.1, 0.16.0, 0.17.0). A session binds
to one of them, so publishing without restarting leaves the OLD build handling
every call. The owner's test session was still on 0.15.1: old prompt AND old
cache key, hence a cache hit and identical text.

Nothing on screen said so. `lens-status` compared repo vs running, which is the
right pair for "did I forget to publish" but not for "did I forget to restart" —
in that case the repo is current, the publish succeeded, and the only
discrepancy is invisible.

`lens-status` now also lists the versions present in the plugin cache and warns
when the newest is not the one that handled the last call. Running it right
after this landed printed exactly the missing sentence, and `Tier 2:命中缓存`
next to it independently confirmed the cache-hit path.

Fourth instance of one shape: a value that is stale but presented as current.
The rule this project keeps re-learning is to make the stale case SAY it is
stale, rather than to make it rarer.

Version 0.17.1.

## M22 (2026-08-14): the prompt fix, actually measured

Rerun of the four cases on 0.17.1, with a restart, so the new prompt and the
prompt-keyed cache were both live. Three distinct outcomes:

- **#2 `shred -u -z` — fixed.** Old: "`-u` controls how many times it
  overwrites" (false). New: "securely deletes the file — overwrites the
  contents several times, fills with zeros, then removes the file itself."
  It stopped naming flags and described the resulting behaviour, which is both
  correct and more useful. That is exactly the shape the prompt now asks for.
- **#17 `git -C .../norepo reset --hard` — fixed.** It now says the path does
  not look like a real repository ("`norepo` suggests it does not exist") and
  the command will probably fail outright. The "say so when the target
  evidently does not exist" clause did the work.
- **#14 `sudo -n rm` — STILL WRONG.** Still "runs without needing to type a
  password". The wording shifted slightly, proving a fresh call rather than a
  cache hit, so the model simply believes this. The prompt said not to explain
  a flag "unless you are certain" — useless guidance, because the model is
  always certain. Tightened to a flat prohibition: never explain what a flag
  means, describe the resulting behaviour instead. `-n` remains the standing
  counter-example to watch.
- **#22 `aws s3 rm` — no AI note at all.** `lens-status` reported
  `Tier 2:无回复(超时或 API 出错)`. This is the fail-open path working: Tier 2
  missed its 3s deadline, and the dialog still rendered with the full Tier 1
  explanation. Worth stating plainly because it looks like a regression on
  screen and is not one — though it is the first observed timeout in normal
  use, so the deadline is worth watching.

Lesson beyond this project: "unless you are certain" is not a constraint on a
model. A prohibition has to name the behaviour to avoid, not the confidence
level under which to avoid it.

Version 0.18.0.

## M23 (2026-08-14): the flag errors were the model, not the prompt

`sudo -n` survived three rounds of prompt tightening — soft guidance, then an
"unless you are certain" hedge, then a flat prohibition on explaining flags at
all. The third round it named the flag anyway. So the prompt was measured
against the alternative instead of tightened a fourth time.

Same prompt, same command, two models, two runs each:

| | `sudo -n rm ...` | median latency |
|---|---|---|
| `claude-haiku-4-5` | wrong 2/2 — "does not need a password" | 1.2s |
| `claude-sonnet-5` | right 2/2 — "fails outright if there is no passwordless rule" | 2.5s |

A capability limit, not a wording problem. Defaults changed to `claude-sonnet-5`
with the deadline raised 3.0s → 5.0s: sonnet's slowest measured call was 3.5s,
so the old deadline would have paid for calls whose answers never rendered.

**The deadline is the dialog's latency** — the hook runs before the prompt
appears, so this trade buys correctness with ~1.3s of extra wait on every
Tier 2 call. Worth it: the reader is about to read the sentence carefully, and
a confidently wrong one spends the trust the rule-verified half is there to
earn. Owner made this call explicitly; haiku stays a one-line config change.

Also fixed a test that pinned `timeout_seconds == 3.0` as a literal. The
assertion is about the deadline being passed through to the request, not about
its value, so it now reads DEFAULT_CONFIG.

Version 0.20.0 (shipped together with M24).

## M24 (2026-08-14): the notification channel is gone

Owner: "把 mac 通知弹窗那个去掉吧,没啥用." Removed rather than left switched
off. It was built in M6 for a real reason — back then `systemMessage` did not
render, so a notification was the only way the explanation could reach a human.
`PreToolUse` `"ask"` replaced that: the explanation now lands in the dialog the
user is already looking at, which is strictly better placement. What the
notification retained was the auto-allowed case (flagged calls that never show
a dialog), and in practice that turned out not to be worth a second channel.

Removed: the `notify` config block and its validation, `maybe_notify`,
`send_desktop_notification`, `_osa_escape`, `session_label` and `_TITLE_KEYS`
(only the notification path read session titles), `_SEVERITY_THRESHOLDS`, the
`notify()` M4 localhost-panel stub that had been a no-op since it was written,
tests/test_notify.py, and the README sections in both languages.

`_scan_transcript` stays — `task_context` shares it. `notify_subject` was
renamed `detail_subject`, which is what it had actually been since detail
extraction landed.

330 tests (down from 354; the 24 removed were all notification tests). An
existing `notify` block in a user config is simply ignored.

## M23 (2026-08-14): the CLI, both halves

Owner ran the two CLI probes. They answered opposite questions.

**Interactive terminal CLI: works, and the M1-era doubt is closed.** A real
session rendered

    Hook PreToolUse:Bash requires confirmation for this command:
    🔴 高危 · /dev/null · …（AI 解读：…）  [plugin:permission-lens]
    Do you want to proceed?

so the reason renders inline, attributed to the plugin, and `"ask"` floors the
decision at a prompt exactly as on Desktop. The old "the CLI never fired the
hook" note was about `PermissionRequest`, a different event, and does not carry
over to `PreToolUse`.

**Headless `-p`: the plugin was acting as a gatekeeper.** `claude -p "Run: sudo
-n rm /tmp/pl-check/sudo-target.txt" --allowedTools "Bash(sudo:*)"` — the tool
explicitly allowlisted — came back: "The command was blocked by a permission
hook … It didn't execute." Nobody is present to answer, so `"ask"` does not
float the decision up to a human; it fails the call. The code never emitted
deny, and the effect was a denial anyway. That is the core invariant broken in
practice while intact on paper.

Probed for a signal rather than guessing: under `claude -p`,
`CLAUDE_CODE_ENTRYPOINT=sdk-cli` (Desktop reports `claude-desktop`). New
`ask.non_interactive`, default `"silent"`: on an entrypoint in an explicit
non-interactive set, matched calls print `{}`. The set is an exact-match
allowlist and an unknown or absent value keeps today's behavior, because the
two errors are not symmetric — mistaking interactive for headless costs an
explanation, mistaking headless for interactive costs a working command.

**Same screenshot, second bug: `dd if=/dev/zero of=/dev/null` was 🔴 high.**
`/dev/null` is not storage; that command is the canonical harmless no-op. The
rule matched any `of=/dev/`. Pseudo-devices are now excluded. Notably Tier 2
had already caught it live — "writes to /dev/null, which discards data, so no
real file or device is changed" — the third instance of the model correcting a
category-level rule on a specific instance, after 127.0.0.1 and the local npm
registry. Tier 2 flagging a Tier 1 over-claim is turning out to be a reliable
signal worth mining rather than a curiosity.

Version 0.21.0. 336 tests.

**M23 confirmed live.** The same headless command now executes: it reaches
`sudo`, which exits with "a password is required". The plugin is out of the
decision and the allowlist governs again — previously the hook itself reported
"It didn't execute".

Incidental: the CLI's own explanation of the failure — "`sudo -n` runs
non-interactively and refuses to prompt, so it exits rather than asking for
your password" — is precisely the semantics Tier 2 keeps inverting ("runs
without needing a password"). Independent confirmation that the M22 finding is
a model error and not a misreading, and the sharpest available statement of
what the right answer looks like. `sudo -n` stays the standing counter-example.

## M24 (2026-08-14): the fix that invalidated its own test case

Owner asked whether `dd if=/dev/zero of=/dev/null` wasn't section 1's own case.
It was — case 2, chosen precisely BECAUSE /dev/null is harmless, so a 🔴 rule
could be exercised without risking a disk. Excluding pseudo-devices in M23 was
right, and it silently made that case unfirable: the checklist went on
promising a red dialog that could no longer appear.

Both halves are true at once. A red badge on a harmless command spends the
credibility the badge needs; and section 1 still needs a target that fires the
dangerous rule while staying safe to allow. Case 3 already had the right shape —
a device path that does not exist — so case 2 now uses
`/dev/pl-check-no-such-device`. It fires dd-to-device at high, names the device
correctly, and fails on its own (/dev is not writable and the device is not
there).

**The checklist is now verified by the suite, not by eye.** `test_manual_cases.py`
parses the doc and re-checks every case against the analyzer: section 1 must be
high, section 2 must match the severity printed in its table, section 3 must
match nothing. A drifted checklist is worse than none — each stale row reads as
a plugin bug during testing, which is exactly the confusion this cost.

Writing that test immediately caught a second, quieter defect: section 3 is a
numbered list rather than a table, so the table pattern matched **zero** rows
and all 35 false-positive defenses passed vacuously. Only the
`test_sections_are_not_empty` guard exposed it. A parser that matches nothing
is the failure mode every doc-derived test has, and asserting on the row count
is the cheapest defense.

Version 0.22.0. 374 tests + 74 checklist cases.
