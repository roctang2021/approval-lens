#!/usr/bin/env python3
"""Check local documentation links and example syntax without executing examples."""
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
FENCES = re.compile(r"^[ \t]*```.*?^[ \t]*```", re.M | re.S)
EXAMPLES = re.compile(r"^[ \t]*```(json|bash)\n(.*?)^[ \t]*```", re.M | re.S)


def anchors(text):
    headings = re.findall(r"^#+\s+(.+)$", FENCES.sub("", text), re.M)
    counts, result = {}, set()
    for heading in headings:
        base = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(base, 0)
        result.add(f"{base}-{count}" if count else base)
        counts[base] = count + 1
    return result


def main():
    errors, links, examples = [], 0, 0
    files = [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md"),
             *ROOT.glob("scripts/**/*.md")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        label = path.relative_to(ROOT)
        for kind, code in EXAMPLES.findall(text):
            examples += 1
            if kind == "json":
                try:
                    json.loads(code)
                except ValueError as exc:
                    errors.append(f"{label}: invalid JSON example: {exc}")
            else:
                result = subprocess.run(["bash", "-n"], input=code, text=True,
                                        capture_output=True, timeout=10)
                if result.returncode:
                    errors.append(f"{label}: {result.stderr.strip()}")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", FENCES.sub("", text)):
            if urlsplit(target).scheme or target.startswith("//"):
                continue
            dest, _, fragment = unquote(target).partition("#")
            linked = (path.parent / dest).resolve() if dest else path
            links += 1
            if not linked.exists():
                errors.append(f"{label}: missing file {target}")
            elif fragment and linked.suffix == ".md":
                if fragment not in anchors(linked.read_text(encoding="utf-8")):
                    errors.append(f"{label}: missing heading {target}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"ok: {links} local links and {examples} JSON/shell examples")


if __name__ == "__main__":
    main()
