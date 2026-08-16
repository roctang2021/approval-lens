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
    "tier2_never": "no risky call has reached it yet",
}


def _text(locale, key):
    return pl.ui_text(locale, key, FALLBACK[key], section="status")


def _version():
    manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "?")
    except Exception:
        return "?"


def _installed_versions():
    """Versions sitting in the plugin cache, newest last.

    `claude plugin update` writes each build to its own version-named directory
    and several coexist. A session binds to one of them, so "installed" and
    "running" are different questions — publishing without restarting leaves the
    old build handling every call, with nothing on screen saying so.
    """
    root = Path.home() / ".claude" / "plugins" / "cache"
    found = set()
    try:
        for manifest in root.glob("*/permission-lens/*/.claude-plugin/plugin.json"):
            try:
                v = json.loads(manifest.read_text(encoding="utf-8")).get("version")
            except Exception:
                continue
            if isinstance(v, str) and v:
                found.add(v)
    except Exception:
        return []
    return sorted(found, key=_version_key)


def _version_key(v):
    return [int(part) if part.isdigit() else -1 for part in v.split(".")]


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

    # Two versions matter and they routinely disagree: the checkout, and the
    # build that actually handled the last call (installed copy + app restart).
    # Reporting only the former is how "I fixed that already" turns into an
    # hour of confusion.
    repo, running = _version(), str(hb.get("running") or "")
    installed = _installed_versions()
    newest = installed[-1] if installed else ""
    if running and running != repo:
        print(f"Permission Lens {running}（正在运行）· 仓库是 {repo} —— "
              f"重启 Claude 后新版才生效")
    else:
        print(f"Permission Lens {repo}")
    # The trap this catches: publish succeeded, so the newest build is on disk
    # and the repo looks current, yet every call is still handled by whatever
    # version the session bound to at startup.
    # Strictly newer, not merely different: running a build that is AHEAD of the
    # cache is the normal state when testing from the checkout, and warning
    # about it told the reader to restart in order to downgrade.
    if newest and running and _version_key(newest) > _version_key(running):
        print(f"⚠️  已安装 {newest}，但最近一次调用由 {running} 处理"
              f" —— 重启 Claude Code 才会切过去")
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
        # From the last call that actually reached Tier 2 — benign calls never
        # do, and they must not overwrite this.
        t2 = hb.get("tier2") if isinstance(hb.get("tier2"), dict) else {}
        outcome = t2.get("outcome")
        key = f"tier2_{outcome}" if outcome in pl.TIER2_OUTCOMES else "tier2_never"
        state = _text(locale, key)
        if isinstance(t2.get("ts"), (int, float)):
            state += f" ({_age(locale, max(0, time.time() - t2['ts']))})"
        print(_text(locale, "tier2").format(state=state))


if __name__ == "__main__":
    main()
