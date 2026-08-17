# Contributing

```bash
./scripts/check.sh
```

That runs the suite, drives the real `uv run hooks/permission_lens.py` subprocess
path, renders every locale, and validates the plugin manifest. It is the whole
gate — if it passes, open the PR.

## Invariants

These are not style preferences. A change that breaks one is wrong even if the
tests pass, so `tests/test_output_contract.py` pins them.

1. **Never a gatekeeper.** The only decision emitted is `"ask"`. Never
   `"allow"`, never `"deny"`. The plugin can make sure a human is asked; it can
   never answer for them.
2. **Fail open on every path.** Exactly one JSON object on stdout, exit 0
   always. On `PreToolUse`, exit 2 *blocks the tool call* — so an internal error
   must degrade to `{}`, not to a denial.
3. **Silence below the threshold.** `{}` means allowlists and native dialog
   behave exactly as if the plugin were not installed.
4. **The model never decides.** Severity and the ask decision come only from
   the offline rules. Tier 2 text can be appended, filtered, or dropped — it can
   never change what fired.
5. **Failures leave a trace.** Every `except` that swallows something calls
   `log_debug`. This project lost hours twice to side effects that quietly
   stopped working; a silent failure is a bug even when the fallback is correct.

## Layout

```
hooks/
  permission_lens.py   Claude Code adapter + hook entry point (~110 lines)
  lens/                the engine — no host knows anything about Claude Code
    core.py            assess(event, config, surface) -> Assessment
    parsing.py         Parsed / SimpleCommand: telling code from text
    rules.py           loading rule data, deciding what matches
    predicates.py      conditions a regex cannot express + has_flag
    render.py          matched rules -> the one dialog line
    tier2.py           the optional model call, its cache, and its guard
    locales.py         all user-visible text, per language
    config.py          validate_config is the ONLY config constructor
    heartbeat.py       liveness + per-day counters
    context.py         the developer's request (opt-in, off by default)
```

## Adding a rule

1. Add the matching logic to `hooks/rules.yaml` (Bash), `rules_web.yaml`
   (WebFetch URL), or `rules_path.yaml` (Write/Edit path or content).
2. Add `explanation` and `risk` under `rules.<id>` in `hooks/locales/en.yaml`.
   `tests/test_locales.py` fails until you do. Other languages fall back to
   English per key, so translating is optional and never blocking.
3. Add a positive case to `tests/corpus/dangerous.yaml`. `test_rules.py`
   asserts every rule has one.
4. Add a negative case to `tests/corpus/benign.yaml` if the rule could plausibly
   over-match — most false positives this project has shipped were rules that
   looked obviously narrow.

Prefer the structural vocabulary over a cleverer regex:

| field | meaning |
|---|---|
| `verb:` | only fire if some stage actually RUNS this program |
| `not_verb:` | a verb that makes the match inert (`echo` printing a path) |
| `scope: argv` | match individual argv tokens; tokens with spaces are prose |
| `scope: redirect` | match real `>`/`>>` targets, found quote-aware |
| `scope: segment` | match one pipeline stage rather than the whole command |
| `without_flags:` | flags that disarm the rule (`--dry-run` transfers nothing) |
| `predicate:` | a named function in `predicates.py` for the rest |

Every regex trick this project has had to remove was a structural question in
disguise: is that text code or data, is that path an argument or a sentence, is
that `>>` a redirect or a character inside a string.

### Rule copy

The `risk` line is what the reader acts on, so it must be true of the specific
call, not just of the category. A rule was deleted for saying HTTP traffic can
be read in transit when the only tool it applied to upgrades to HTTPS first, and
two more were narrowed for calling `dd of=/dev/null` and `npm publish --dry-run`
dangerous. Copy that asserts a consequence the command cannot have spends the
credibility every other rule depends on.

Plain words, one sentence, no jargon, no labels to decode. Say what happens and
why it matters — not "modifies shell rc" but "code added here runs every time
you open a terminal".

## Adding a language

Copy `hooks/locales/en.yaml` to `<code>.yaml` and translate. Nothing else — the
loader picks it up, `available_langs()` accepts it, and any key you leave out or
blank falls back to English individually. `tests/test_locales.py` checks
structure, not completeness.

## Adding a host

`assess(event, config, surface)` is the whole engine and reads no environment.
An adapter's job is four things: turn the host's event into
`{"tool_name", "tool_input"}`, decide `SURFACE_INTERACTIVE` vs
`SURFACE_HEADLESS`, express the verdict in the host's protocol, and preserve the
invariants above. `hooks/permission_lens.py` is 110 lines and does exactly that
for Claude Code.

Before writing one, **probe the host and write down what you measured** —
whether a hook fires at all, whether it can attach text to an approval prompt,
and what happens to that text with no human present. Every significant mistake
in this project's history came from assuming one of those answers instead of
testing it; `NOTES.md` is the log of what was actually measured, and a new
adapter belongs in it.

## Testing

`scripts/manual-test-cases.md` is the human checklist, generated from the real
rules and verified against the analyzer by `tests/test_manual_cases.py` — a
checklist that has drifted is worse than none, because every stale row reads as
a plugin bug.

**Probes must be harmless even if approved.** Not "harmless because you will
click Deny" — permission modes change, and a checklist that assumes a human
gatekeeper is a checklist that eventually deletes something. Use targets that
do not exist (`/dev/pl-check-no-such-device`, `pl-check-no-such-remote`) or live
under `/tmp/pl-check/`. Path rules match a path *shape*, so a stand-in produces
the identical dialog while touching nothing real.
