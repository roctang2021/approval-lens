"""Best-effort local invocation status and daily counters."""
import json
import os
import time
import traceback

from .paths import PLUGIN_MANIFEST
from .util import cache_dir, log_debug

# Store timestamps, tool name, severity and confirmation/model outcomes.
# Commands, URLs and file paths are omitted. Read with scripts/approval-lens-status.py.

HEARTBEAT_FILE = "heartbeat.json"
_COUNT_KEYS = ("total", "high", "medium", "low", "none", "asked")
_VERSION = None


def plugin_version():
    """Read the manifest beside the running code, which may be an installed copy."""
    global _VERSION
    if _VERSION is None:
        _VERSION = ""
        try:
            with open(PLUGIN_MANIFEST, "r", encoding="utf-8") as fh:
                _VERSION = str(json.load(fh).get("version") or "")
        except FileNotFoundError:
            pass  # running outside a plugin checkout is normal
        except Exception:
            log_debug("plugin manifest %s unreadable: %s" % (PLUGIN_MANIFEST, traceback.format_exc()))
    return _VERSION


def record_heartbeat(tool, matches, asked, tier2_outcome):
    try:
        path = cache_dir() / HEARTBEAT_FILE
        now = time.time()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        state = {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                state = loaded
        except FileNotFoundError:
            pass  # first run: no heartbeat yet is the normal case
        except Exception:
            # Start fresh after corruption; retain a debug diagnostic.
            log_debug("heartbeat %s unreadable, starting fresh: %s" % (path, traceback.format_exc()))
        counts = state.get("counts") if state.get("today") == today else None
        if not isinstance(counts, dict):
            counts = {}
        counts = {k: _nonneg_int(counts.get(k)) for k in _COUNT_KEYS}
        severity = matches[0]["severity"] if matches else None
        bucket = severity if severity in ("high", "medium", "low") else "none"
        counts["total"] += 1
        counts[bucket] += 1
        if asked:
            counts["asked"] += 1
        # Keep the latest model outcome across below-threshold calls, which do
        # not consult the model and would otherwise replace its status with off.
        tier2 = state.get("tier2") if isinstance(state.get("tier2"), dict) else {}
        if asked:
            tier2 = {"outcome": tier2_outcome, "ts": now}
        fresh = {
            "version": 1,
            "running": plugin_version(),  # which build actually handled this call
            "updated": now,
            "today": today,
            "counts": counts,
            "tier2": tier2,
            "last": {"ts": now, "tool": tool, "severity": severity, "asked": bool(asked)},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(fresh, fh, ensure_ascii=False)
        os.replace(tmp, path)  # atomic; a concurrent hook loses a count, never the file
    except Exception:
        log_debug("heartbeat: " + traceback.format_exc())


def _nonneg_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
