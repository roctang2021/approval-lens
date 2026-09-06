# Contributing

Approval Lens explains pending coding-agent actions so users can make informed
approval decisions. Claude Code is the current integration; see
[the intended experience and adapter boundaries](docs/architecture.md).

## Check a change

```bash
./scripts/check.sh
```

The script runs pyflakes, tests, documentation checks, the real uv hook entry
point and locale rendering. It validates both manifests when the Claude CLI is
installed; CI installs the reviewed CLI version for that check.
For changes to delivery or approval behavior, use the [live checklist](scripts/manual-test.md).
The current [release review](docs/release-review.md) records verified checks and
the remaining publication requirements.

## Behavior to preserve

- Rules determine severity; model text cannot change it.
- Below-threshold calls do not request extra confirmation.
- The Claude adapter emits `ask` or `{}`, not allow or deny. Handled errors exit
  zero; known headless entrypoints default to silence.
- Keep file content and user-request transmission behind their own settings.
- Optional work must not break the assessment. Unexpected swallowed errors
  should call `log_debug`; expected missing files need no diagnostic.

## Add a rule

1. Add matching logic to `hooks/rules.yaml`, `rules_web.yaml` or `rules_path.yaml`.
2. Add its `explanation` and `risk` in `hooks/locales/en.yaml`.
3. Add a positive example to `tests/corpus/dangerous.yaml` (or the relevant
   WebFetch/Write/Edit tests), and a near-miss that must stay silent.
4. For guards, wrappers or substitutions, add mixed-stage examples to
   `tests/corpus/evasion.yaml`.

| Field | Meaning |
| --- | --- |
| `verb` / `not_verb` | Include or exclude actual program names in a stage |
| `scope: segment` | Default: match normalized words; prose operands stay opaque |
| `scope: argv` | Match individual path-like arguments |
| `scope: redirect` | Match actual output targets |
| `scope: pipeline` + `pipe_to` | Match a source connected to a downstream program |
| `scope: process` + `pipe_to` | Match a source in `<(...)` passed to a receiver |
| `without_flags` | Check effective no-op flags, including values and overrides |
| `predicate` | Function returning the matching SimpleCommand, or None |

Use parser structure to distinguish code from text. Pipeline rules match real
connections; quoted examples do not supply verbs or receivers. Each match keeps
its `_match_subject` for target extraction. Never store invocation evidence on
cached rule definitions.

## Write copy and comments

- Start user docs with the task, current support and next action. Keep detailed
  settings in the configuration reference and investigation history in the archive.
- Write for the person facing an approval prompt: explain the action, concrete
  target and relevant effect. Relate it to the user's task only when context
  supports that connection. A risk label alone does not explain an operation.
- State current behavior separately from plans. A shared module is not proof
  that another host is supported, or that the assessment has no side effects.
- Make `explanation` a short action label. Make `risk` one sentence with the
  consequence that the rule can establish; qualify outcomes that depend on
  permissions, configuration or execution.
- Avoid claims such as guaranteed recovery failure, malicious intent inferred
  from encoding, or public visibility inferred solely from a publish command.
- Keep comments about constraints, edge cases and reasons for non-obvious code.
  Move dated debugging stories to the engineering archive. Avoid repeating the
  product pitch, restating the code or emphasizing words with capitals.
- Use purpose-based labels at approval time, such as "What this does". Explain
  the model source, opt-in and data handling in setup documentation. Prompts
  should request observable facts and allow uncertainty.

## Add a language

Copy `hooks/locales/en.yaml` to `<code>.yaml`, translate values and preserve keys
and placeholders. Missing or blank values fall back to English. Mark generated
translations as needing language review. Run the locale and status tests.

## Add an adapter

Normalize actions and context at the host boundary, then map the assessment to
the host's approval protocol. Verify interception, reason display, allowlist
interaction and headless behavior before documenting support. Keep the shared
rules independent of one host's event names or transcript format.

## Test inputs

Analyzer tests pass commands as data. Live probes must remain safe if approved:
use `.invalid` hosts or controlled scratch files, and inspect a probe's effects
before running it. `scripts/gen-manual-cases.py` exports validated corpus rows to
`$TMPDIR/al-cases.json` for comparison. Update `scripts/manual-test-cases.md`
when documented expectations change; its severity checks run in the test suite.
