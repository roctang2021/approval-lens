#!/usr/bin/env python3
"""Permission Lens liveness check: last analyzed call + today's counters.

Reads the heartbeat state the hook updates on every analyzed invocation
(`~/.cache/permission-lens/heartbeat.json`; honors PERMISSION_LENS_CACHE_DIR).
A clean permission dialog is indistinguishable from a dead hook — this is the
discriminator. Stdlib only: `python3 scripts/lens-status.py`.
"""
import json
import os
import time
from pathlib import Path

DEFAULT_CACHE_DIR = "~/.cache/permission-lens"
DEFAULT_CONFIG_PATH = "~/.config/permission-lens/config.json"

TEXT = {
    "en": {
        "none": "no match",
        "asked": "dialog forced",
        "silent": "silent",
        "last": "last check {age} ({tool} · {what})",
        "today": "today: {total} checked · 🔴 {high} · 🟡 {medium} · 🟢 {low} · no match {none} · dialogs forced {asked}",
        "empty": ("no invocations recorded yet — run any Bash/WebFetch/Write/Edit "
                  "in a plugin-enabled session first (heartbeat: {path})"),
        "stale_day": "(counters are from {day}, not today)",
        "s": "{n}s ago", "m": "{n} min ago", "h": "{n} h ago", "d": "{n} d ago",
    },
    "zh": {
        "none": "无命中",
        "asked": "已弹框",
        "silent": "未弹框",
        "last": "最近一次检查 {age}（{tool} · {what}）",
        "today": "今日已检查 {total} 次 · 🔴 {high} · 🟡 {medium} · 🟢 {low} · 无命中 {none} · 弹框 {asked}",
        "empty": ("还没有任何调用记录——先在装了插件的会话里跑一条 "
                  "Bash/WebFetch/Write/Edit（心跳文件:{path}）"),
        "stale_day": "(计数属于 {day},不是今天)",
        "s": "{n} 秒前", "m": "{n} 分钟前", "h": "{n} 小时前", "d": "{n} 天前",
    },
}

SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _lang():
    cfg = _read_json(os.path.expanduser(
        os.environ.get("PERMISSION_LENS_CONFIG") or DEFAULT_CONFIG_PATH))
    return "zh" if cfg.get("lang") == "zh" else "en"


def _version():
    manifest = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    return _read_json(manifest).get("version", "?")


def _age(t, seconds):
    if seconds < 90:
        return t["s"].format(n=int(seconds))
    if seconds < 90 * 60:
        return t["m"].format(n=int(seconds // 60))
    if seconds < 36 * 3600:
        return t["h"].format(n=int(seconds // 3600))
    return t["d"].format(n=int(seconds // 86400))


def main():
    t = TEXT[_lang()]
    cache = Path(os.path.expanduser(
        os.environ.get("PERMISSION_LENS_CACHE_DIR") or DEFAULT_CACHE_DIR))
    hb_path = cache / "heartbeat.json"
    hb = _read_json(hb_path)
    print(f"Permission Lens {_version()}")
    last = hb.get("last")
    if not isinstance(last, dict) or not isinstance(last.get("ts"), (int, float)):
        print(t["empty"].format(path=hb_path))
        return
    sev = last.get("severity")
    what = f"{SEVERITY_EMOJI[sev]} {sev}" if sev in SEVERITY_EMOJI else t["none"]
    what += " · " + (t["asked"] if last.get("asked") else t["silent"])
    print(t["last"].format(age=_age(t, max(0, time.time() - last["ts"])),
                           tool=last.get("tool", "?"), what=what))
    counts = hb.get("counts") if isinstance(hb.get("counts"), dict) else {}
    line = t["today"].format(**{k: counts.get(k, 0)
                                for k in ("total", "high", "medium", "low", "none", "asked")})
    today = time.strftime("%Y-%m-%d")
    if hb.get("today") and hb["today"] != today:
        line += " " + t["stale_day"].format(day=hb["today"])
    print(line)


if __name__ == "__main__":
    main()
