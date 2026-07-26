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
#   scripts/preview.sh 'rm -rf $HOME/projects'
#   scripts/preview.sh --fetch 'https://user:pass@example.com/x'
#   scripts/preview.sh --write '/Users/x/.ssh/config'
#   scripts/preview.sh --edit '/etc/sudoers'
set -euo pipefail
cd "$(dirname "$0")/.."

tool=Bash; field=command; value=${1:-}
case "${1:-}" in
  --fetch) tool=WebFetch; field=url;       value=${2:-} ;;
  --write) tool=Write;    field=file_path; value=${2:-} ;;
  --edit)  tool=Edit;     field=file_path; value=${2:-} ;;
  -h|--help|"") sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
[ -n "$value" ] || { echo "missing value for $tool" >&2; exit 1; }

# A scratch cache dir keeps previews out of the real heartbeat and Tier 2 cache,
# so running this never disturbs what `lens-status` reports.
export PERMISSION_LENS_CACHE_DIR="${TMPDIR:-/tmp}/pl-preview-cache"

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
