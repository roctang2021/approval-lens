"""Liveness and per-day counters, so a clean dialog is
distinguishable from a dead hook."""
import json
import os
import time
import traceback

from .paths import PLUGIN_MANIFEST
from .util import cache_dir, log_debug

# ── heartbeat ─────────────────────────────────────────────────────────────────
#
# Answers "is the plugin alive, and was that call actually checked?" without
# touching the dialog: a clean dialog is otherwise indistinguishable from a
# dead hook. Every analyzed invocation updates one small local state file —
# timestamps, tool name, top severity, ask outcome; NEVER commands, URLs, or
# paths. Best-effort SIDE EFFECT like the notifier: failures are swallowed,
# stdout and exit codes untouched. Read it with scripts/lens-status.py.

HEARTBEAT_FILE = "heartbeat.json"
_COUNT_KEYS = ("total", "high", "medium", "low", "none", "asked")
_VERSION = None


def plugin_version():
    """Version of the code actually executing — not whatever is checked out.

    The installed plugin runs from a versioned copy under ~/.claude/plugins,
    so a repo that is ahead of the last `claude plugin update` (or of the last
    app restart) behaves like the older one. Recording it here is what lets
    lens-status say so instead of reporting the repo's number.
    """
    global _VERSION
    if _VERSION is None:
        _VERSION = ""
        try:
            with open(PLUGIN_MANIFEST, "r", encoding="utf-8") as fh:
                _VERSION = str(json.load(fh).get("version") or "")
        except Exception:
            pass
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
        except Exception:
            pass  # missing/corrupt heartbeat -> start fresh
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
        # Tier 2 status is kept SEPARATELY from `last`, and only refreshed by
        # calls that actually reached the Tier 2 stage. Benign calls (the vast
        # majority) never consult Tier 2, so folding it into `last` would show
        # "off" almost always and hide the real outcome.
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
