#!/usr/bin/env bash
# Preview explanations without executing the supplied operation.
# --all uses offline rules; single previews use the current model settings.
#
# Usage:
#   scripts/preview.sh --all
#   scripts/preview.sh 'rm -rf $HOME/projects'
#   scripts/preview.sh --fetch 'https://user:pass@example.invalid/x'
#   scripts/preview.sh --write '/tmp/al-check/.ssh/config'
#   scripts/preview.sh --edit '/tmp/al-check/sudoers'
set -euo pipefail
cd "$(dirname "$0")/.."

# A scratch cache dir keeps previews out of the real heartbeat and Tier 2 cache,
# so running this never disturbs what `approval-lens-status` reports.
export APPROVAL_LENS_CACHE_DIR="${TMPDIR:-/tmp}/al-preview-cache"

if [ "${1:-}" = "--all" ]; then
  # Read corpus input directly to keep preview commands out of the host hook.
  exec uv run --quiet --with pyyaml python - <<'PY'
import sys, yaml
sys.path.insert(0, "hooks")
import lens as al
LANG = (al.load_config() or {}).get("lang", "en")
gate = al.load_config()["ask"]["min_severity"]
cases = yaml.safe_load(open("tests/corpus/dangerous.yaml"))["commands"]
shown = {"high": [], "other": []}
for e in cases:
    hits = al.analyze_command(al.Parsed(e["command"]))
    if not hits:
        continue
    sev = hits[0]["severity"]
    reason = al.render_reason(hits, lang=LANG,
                              detail=al.extract_detail(hits[0], None, e["command"]))
    asks = al.passes_threshold(hits, gate)
    shown["high" if asks else "other"].append((e["command"], reason))
print(f"当前阈值 ask.min_severity = {gate}，语言 = {LANG}\n")
print(f"=== 达到确认阈值的 {len(shown['high'])} 条 " + "=" * 30)
for cmd, reason in shown["high"]:
    print(f"\n$ {cmd}\n  {reason}")
print(f"\n\n=== 命中但低于确认阈值的 {len(shown['other'])} 条 " + "=" * 12)
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
  -h|--help|"") sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
[ -n "$value" ] || { echo "missing value for $tool" >&2; exit 1; }

TOOL="$tool" FIELD="$field" VALUE="$value" python3 -c '
import json, os
print(json.dumps({"tool_name": os.environ["TOOL"],
                  "tool_input": {os.environ["FIELD"]: os.environ["VALUE"]}}))
' | uv run --quiet hooks/approval_lens.py | python3 -c '
import json, sys
out = json.load(sys.stdin).get("hookSpecificOutput")
if not out:
    print("（未请求额外确认）")
else:
    print(out["permissionDecisionReason"])
'
