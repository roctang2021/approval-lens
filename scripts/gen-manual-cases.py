#!/usr/bin/env python3
"""Export validated analysis examples to $TMPDIR/al-cases.json.

Commands are analyzed as text, never executed. The JSON rows help maintain
manual-test-cases.md; this script does not rewrite that document.
"""
import json
import os
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "hooks"))
import lens as al  # noqa: E402

locale = al.load_locale("zh")
corpus = yaml.safe_load((REPO / "tests/corpus/dangerous.yaml").read_text(encoding="utf-8"))["commands"]
benign = yaml.safe_load((REPO / "tests/corpus/benign.yaml").read_text(encoding="utf-8"))["commands"]
rows = {"high": [], "mid": [], "silent": []}
seen = set()
for entry in corpus:
    rule_id, command = entry["rule"], entry["command"]
    if rule_id.startswith(("web-", "path-", "content-")):
        continue
    hits = al.analyze_command(al.Parsed(command))
    ids = [match["id"] for match in hits]
    assert rule_id in ids, f"corpus drift: {command!r} -> {ids}; expected {rule_id}"
    if command in seen:
        continue
    seen.add(command)
    group = "high" if hits[0]["severity"] == "high" else "mid"
    rows[group].append((command.replace("|", "\\|"), rule_id,
                        al.rule_text(locale, rule_id, "explanation"),
                        al.extract_detail(hits[0], None, command),
                        "仅分析", "不执行示例命令"))

for entry in benign:
    if not entry.get("clean"):
        continue
    command = entry["command"]
    hits = al.analyze_command(al.Parsed(command))
    assert not hits, f"unexpected match: {command!r} -> {[m['id'] for m in hits]}"
    rows["silent"].append(command.replace("|", "\\|"))

output = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "al-cases.json"
output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"已分析：高危 {len(rows['high'])}，中低危 {len(rows['mid'])}，无匹配 {len(rows['silent'])}。未执行示例命令。")
print(f"数据已写入 {output}")
