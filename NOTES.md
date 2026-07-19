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
- **Installed-version discrepancy vs docs**: the docs describe a newer CLI. On
  v2.1.119 the validator has **no `--strict` flag** (documented for a later
  version) and it rejects `$schema` and `displayName` as *errors* rather than
  ignoring them as warnings (the docs' "unrecognized fields are warnings"
  behavior is newer). Both fields were removed from `plugin.json` for
  compatibility. Re-add `displayName` once targeting v2.1.143+.
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

Pending manual verification (needs an interactive TTY / the Desktop app / a live
`-p` run — this autonomous environment can't drive those; see
`scripts/manual-test.md` steps 3–5):

- **CLI rendering**: whether/where `systemMessage` renders relative to the
  permission dialog in an interactive session.
- **Desktop app rendering**: same, in the Desktop app (reads the same settings).
- **`-p` (non-interactive) behavior**: the brief states `PermissionRequest` does
  not fire in `-p` mode (no human to prompt); confirm via `--debug`.

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
