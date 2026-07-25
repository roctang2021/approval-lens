#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6"]
# ///
"""Permission Lens liveness check: last analyzed call + today's counters.

Reads the heartbeat state the hook updates on every analyzed invocation
(`~/.cache/permission-lens/heartbeat.json`; honors PERMISSION_LENS_CACHE_DIR).
A clean permission dialog is indistinguishable from a dead hook — this is the
discriminator.

Run it with `uv run scripts/lens-status.py`. Config and locale come from the
hook module itself, so language and paths always match what the hook does.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import permission_lens as pl  # noqa: E402

SEVERITY_EMOJI = pl.SEVERITY_EMOJI

# English defaults, used if a locale file is missing or PyYAML isn't available.
FALLBACK = {
    "none": "no match", "asked": "dialog forced", "silent": "silent",
    "last": "last check {age} ({tool} · {what})",
    "today": ("today: {total} checked · 🔴 {high} · 🟡 {medium} · 🟢 {low} · "
              "no match {none} · dialogs forced {asked}"),
    "empty": ("no invocations recorded yet — run any Bash/WebFetch/Write/Edit "
              "in a plugin-enabled session first (heartbeat: {path})"),
    "stale_day": "(counters are from {day}, not today)",
    "s": "{n}s ago", "m": "{n} min ago", "h": "{n} h ago", "d": "{n} d ago",
    "tier2": "Tier 2: {state}",
    "tier2_off": "not enabled", "tier2_skipped": "skipped (subject too long)",
    "tier2_cached": "served from cache",
    "tier2_no_credential": "no credential visible to the hook",
    "tier2_empty": "no answer (timeout or API error)", "tier2_ok": "working",
    "tier2_error": "internal error",
}


def _text(locale, key):
    return pl.ui_text(locale, key, FALLBACK[key], section="status")


def _version():
    manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "?")
    except Exception:
        return "?"


def _age(locale, seconds):
    for key, size in (("s", 90), ("m", 90 * 60), ("h", 36 * 3600)):
        if seconds < size:
            unit = {"s": 1, "m": 60, "h": 3600}[key]
            return _text(locale, key).format(n=int(seconds // unit))
    return _text(locale, "d").format(n=int(seconds // 86400))


def main():
    locale = pl.load_locale(pl.load_config()["lang"])
    hb_path = pl._cache_dir() / pl.HEARTBEAT_FILE
    try:
        hb = json.loads(hb_path.read_text(encoding="utf-8"))
        hb = hb if isinstance(hb, dict) else {}
    except Exception:
        hb = {}

    print(f"Permission Lens {_version()}")
    last = hb.get("last")
    if not isinstance(last, dict) or not isinstance(last.get("ts"), (int, float)):
        print(_text(locale, "empty").format(path=hb_path))
        return

    sev = last.get("severity")
    what = f"{SEVERITY_EMOJI[sev]} {pl.severity_label(locale, sev)}" \
        if sev in SEVERITY_EMOJI else _text(locale, "none")
    what += " · " + _text(locale, "asked" if last.get("asked") else "silent")
    print(_text(locale, "last").format(
        age=_age(locale, max(0, time.time() - last["ts"])),
        tool=last.get("tool", "?"), what=what))

    counts = hb.get("counts") if isinstance(hb.get("counts"), dict) else {}
    line = _text(locale, "today").format(**{
        k: counts.get(k, 0)
        for k in ("total", "high", "medium", "low", "none", "asked")})
    today = time.strftime("%Y-%m-%d")
    if hb.get("today") and hb["today"] != today:
        line += " " + _text(locale, "stale_day").format(day=hb["today"])
    print(line)

    # Tier 2 is opt-in and degrades silently by design; without this line
    # "disabled", "no credential" and "network error" are indistinguishable.
    if (pl.load_config().get("llm") or {}).get("enabled"):
        outcome = last.get("tier2")
        key = f"tier2_{outcome}" if outcome in pl.TIER2_OUTCOMES else "tier2_off"
        print(_text(locale, "tier2").format(state=_text(locale, key)))


if __name__ == "__main__":
    main()
