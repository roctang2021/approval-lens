#!/usr/bin/env bash
# Show what the permission dialog WOULD say for a given operation, without
# asking a model to run it and without executing anything.
#
# Why this exists: high-severity cases can't be verified by asking Claude to
# run them. Claude often inspects first, rewrites, or declines outright —
# correct behavior for a destructive command, but it means the tool call is
# never issued, the PreToolUse hook never fires, and "no dialog" looks like a
# plugin miss when nothing was ever analyzed. This feeds the hook directly.
#
# Usage:
#   scripts/preview.sh --all                       # every checklist case at once
#   scripts/preview.sh 'rm -rf $HOME/projects'
#   scripts/preview.sh --fetch 'https://user:pass@example.com/x'
#   scripts/preview.sh --write '/Users/x/.ssh/config'
#   scripts/preview.sh --edit '/etc/sudoers'
set -euo pipefail
cd "$(dirname "$0")/.."

# A scratch cache dir keeps previews out of the real heartbeat and Tier 2 cache,
# so running this never disturbs what `lens-status` reports.
export PERMISSION_LENS_CACHE_DIR="${TMPDIR:-/tmp}/pl-preview-cache"

if [ "${1:-}" = "--all" ]; then
  # Reads the cases from the corpus rather than taking them as arguments, so no
  # dangerous-looking string ever lands on this process's own command line —
  # otherwise previewing the checklist would set off the plugin on itself.
  exec uv run --quiet --with pyyaml python - <<'PY'
import sys, yaml
sys.path.insert(0, "hooks")
import lens as pl
LANG = (pl.load_config() or {}).get("lang", "en")
gate = pl.load_config()["ask"]["min_severity"]
cases = yaml.safe_load(open("tests/corpus/dangerous.yaml"))["commands"]
shown = {"high": [], "other": []}
for e in cases:
    hits = pl.analyze_command(pl.Parsed(e["command"]))
    if not hits:
        continue
    sev = hits[0]["severity"]
    reason = pl.render_reason(hits, lang=LANG,
                              detail=pl.extract_detail(hits[0], None, e["command"]))
    asks = pl.passes_threshold(hits, gate)
    shown["high" if asks else "other"].append((e["command"], reason))
print(f"当前阈值 ask.min_severity = {gate}，语言 = {LANG}\n")
print(f"=== 会弹框的 {len(shown['high'])} 条 " + "=" * 30)
for cmd, reason in shown["high"]:
    print(f"\n$ {cmd}\n  {reason}")
print(f"\n\n=== 命中但低于阈值、不弹框的 {len(shown['other'])} 条 " + "=" * 12)
for cmd, reason in shown["other"]:
    print(f"\n$ {cmd}\n  {reason}")
print("\n（没有执行任何命令，也没有改动心跳计数）")
PY
fi

tool=Bash; field=command; value=${1:-}
case "${1:-}" in
  --fetch) tool=WebFetch; field=url;       value=${2:-} ;;
  --write) tool=Write;    field=file_path; value=${2:-} ;;
  --edit)  tool=Edit;     field=file_path; value=${2:-} ;;
  -h|--help|"") sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
[ -n "$value" ] || { echo "missing value for $tool" >&2; exit 1; }

TOOL="$tool" FIELD="$field" VALUE="$value" python3 -c '
import json, os
print(json.dumps({"tool_name": os.environ["TOOL"],
                  "tool_input": {os.environ["FIELD"]: os.environ["VALUE"]}}))
' | uv run --quiet hooks/permission_lens.py | python3 -c '
import json, sys
out = json.load(sys.stdin).get("hookSpecificOutput")
if not out:
    print("（静默 —— 插件不会干预这次调用）")
else:
    print(out["permissionDecisionReason"])
'
