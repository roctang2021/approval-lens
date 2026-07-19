# Permission Lens

A Claude Code plugin that **explains pending permission prompts** instead of deciding
for you. When Claude Code is about to show a permission dialog for a Bash command,
Permission Lens annotates it with a plain-language explanation and a risk assessment
— then always falls through to the native dialog. You make the call.

> Status: M1 (Tier 1 static analyzer). Full bilingual README lands in M3.

## Try it

```bash
claude --plugin-dir /path/to/permission-lens
```

Then ask Claude to run something that triggers a permission prompt. See
`scripts/manual-test.md` for a test checklist.

## Principles

- **Never a gatekeeper.** The hook never returns an allow/deny decision.
- **Fail open.** Any internal error prints `{}` and exits 0 — your session is never
  blocked or broken by this tool.

MIT — see [LICENSE](LICENSE). Doc-schema notes in [NOTES.md](NOTES.md).
