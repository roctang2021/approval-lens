# Permission Lens

**English** · [中文](#permission-lens-中文)

A Claude Code plugin that **explains pending permission prompts** instead of
deciding for you. When Claude Code is about to show a permission dialog for a
Bash command, Permission Lens annotates it with a plain-language explanation and
a risk assessment — then **always falls through to the native dialog**. You make
the call.

```
🔴 HIGH · Pipes a downloaded script straight into a shell
Risk: Unreviewed remote code runs with your privileges; the server can serve
      different content between review and execution.
🤖 Downloads i.sh from x.example.com and executes it immediately in bash.   ← optional (Tier 2)
```

## Why

Permission dialogs often show a long, opaque shell command that you approve
blind. Permission Lens adds a sentence of plain language and a risk note so the
decision is an informed one. It is **not** a gatekeeper — it never returns
allow/deny, so nothing is ever auto-approved or auto-blocked on your behalf.

## How it works

Two tiers. The first is always on; the second is optional and off by default.

| Tier | What | Cost | Network |
| --- | --- | --- | --- |
| **1 — static analyzer** | 36 bilingual rules (regex + shell-aware predicates) match the command offline and produce the severity/risk lines. | free | none |
| **2 — LLM explainer** *(opt-in)* | One `claude-haiku-4-5` call adds a `🤖` plain-language line, using **your own** API credentials. | your API usage | one HTTPS call, 3s hard timeout, SHA256-cached 7 days |

Tier 2 **augments** Tier 1 — it never replaces it. If the model call is
disabled, times out, errors, or you have no credentials, you still get the full
Tier 1 annotation. The model sees **only the command string** (never your cwd,
session, or transcript).

## Install

Permission Lens is a `PermissionRequest` hook. It needs [`uv`](https://docs.astral.sh/uv/)
on your `PATH` (it fetches its one dependency, PyYAML, on first run).

### Option A — local dev (fastest to try)

```bash
claude --plugin-dir /path/to/permission-lens
```

Then ask Claude to run something that triggers a permission prompt.

### Option B — manual `settings.json` hook

Add to `~/.claude/settings.json` (use an absolute path) and restart Claude Code:

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --quiet /ABSOLUTE/PATH/permission-lens/hooks/permission_lens.py || true",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

The `|| true` guard is load-bearing: it guarantees a broken launcher can never
exit non-zero and accidentally **deny** a permission (exit 2 on
`PermissionRequest` means deny).

### Option C — plugin marketplace

Once this repo is pushed to GitHub, users install it with:

```
/plugin marketplace add <your-org>/permission-lens
/plugin install permission-lens@permission-lens
```

(The repo is its own single-plugin marketplace — see
[`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json).)

## Configuration

Optional. Create `~/.config/permission-lens/config.json`; every key falls back
to its default if missing or invalid, so a broken config can never break the
hook. Full example: [`config.example.json`](config.example.json).

```json
{
  "lang": "en",
  "min_severity_to_annotate": "info",
  "max_message_chars": 500,
  "llm": {
    "enabled": false,
    "model": "claude-haiku-4-5",
    "timeout_seconds": 3.0,
    "api_key_env": "ANTHROPIC_API_KEY",
    "auth_token_env": "ANTHROPIC_AUTH_TOKEN",
    "cache_ttl_days": 7
  }
}
```

| Key | Values | Default | Notes |
| --- | --- | --- | --- |
| `lang` | `"en"` \| `"zh"` | `"en"` | Language of annotations. |
| `min_severity_to_annotate` | `"info"` \| `"low"` \| `"medium"` \| `"high"` | `"info"` | `"info"` annotates everything (incl. the neutral ℹ️ summary); higher values stay silent unless a rule matches at/above that level. |
| `max_message_chars` | 80–9000 | 500 | Hard cap on the annotation length. |
| `llm.enabled` | `true` \| `false` | `false` | Turns on Tier 2. Must be literal `true`. |
| `llm.model` | model id | `"claude-haiku-4-5"` | Any Messages-API model. |
| `llm.timeout_seconds` | 0.1–6.0 | 3.0 | Hard wall-clock deadline for the API call. |
| `llm.api_key_env` / `llm.auth_token_env` | env var name | `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | Where to read your credential (see below). |
| `llm.cache_ttl_days` | 0–365 | 7 | Response cache TTL; `0` disables the cache. |

### Enabling Tier 2 (uses your own account)

Set `"llm": { "enabled": true }` and provide **your own** credential in the
environment — Permission Lens ships no key and talks to no intermediary server.
Resolution order:

1. `ANTHROPIC_API_KEY` — sent as `x-api-key`.
2. `ANTHROPIC_AUTH_TOKEN` — an OAuth bearer token (e.g. from the Anthropic CLI:
   `export ANTHROPIC_AUTH_TOKEN=$(ant auth print-credentials --access-token)`),
   sent as `Authorization: Bearer` with the required `oauth-2025-04-20` beta header.

With neither set, Tier 2 stays silent and you keep Tier 1. Note that Claude
Code's own Pro/Max login credential is **not** used and cannot be — there is no
supported way to bill these API calls to a subscription.

## Testing it locally

- **Run the full check** (tests + hook smoke test + manifest validation):

  ```bash
  scripts/check.sh
  ```

- **Just the test suite** (160 tests, all offline):

  ```bash
  uv run --with pytest --with pyyaml python -m pytest tests/
  ```

- **Feed the hook a command by hand** and see the raw output:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf \"$TMP\"/*"}}' \
    | uv run --quiet hooks/permission_lens.py
  ```

- **Interactive / Desktop / config walkthroughs**: see
  [`scripts/manual-test.md`](scripts/manual-test.md).

## Design principles

- **Never a gatekeeper.** No `hookSpecificOutput`/`decision` is ever emitted.
- **Fail open, always.** Every code path prints one JSON object and exits 0 —
  exit 2 on `PermissionRequest` would deny, so any internal error degrades to a
  silent `{}` and the native dialog shows unannotated.
- **Tier 1 is offline and stdlib-only** (PyYAML aside) and runs in <10ms.
- **Your data stays local.** Tier 2 sends only the command string, over TLS,
  using only your own credentials.

MIT — see [LICENSE](LICENSE). Schema-verification and design notes in
[NOTES.md](NOTES.md).

---

# Permission Lens (中文)

[English](#permission-lens) · **中文**

一个 Claude Code 插件,当权限弹框里是一串看不懂的 shell 命令时,给它**补一段大白话
解释 + 风险评估**,然后**永远放行给原生弹框**——它绝不替你做 allow/deny 决定。要不要
批准,由你来定。

```
🔴 高 · 将下载的脚本直接管道给 shell 执行
风险: 未经审查的远程代码以你的权限运行;服务器可能在你审查与执行之间替换内容。
🤖 从 x.example.com 下载 i.sh 并立即用 bash 执行。   ← 可选(Tier 2)
```

## 为什么

权限弹框经常只显示一条又长又不透明的命令,你只能盲批。Permission Lens 补上一句人话
和一行风险提示,让这个决定是知情的。它**不是**守门员——永不返回 allow/deny,不会替你
自动批准或自动拦截任何东西。

## 工作原理

两层。第一层永远开启;第二层可选,默认关闭。

| 层级 | 内容 | 费用 | 网络 |
| --- | --- | --- | --- |
| **Tier 1 — 静态分析** | 36 条双语规则(正则 + shell 感知谓词)离线匹配命令,产出严重度/风险行。 | 免费 | 无 |
| **Tier 2 — 大模型解释**(需手动开启) | 一次 `claude-haiku-4-5` 调用,用**你自己的**凭据补一行 `🤖` 大白话。 | 记你自己的 API 账户 | 一次 HTTPS 调用,3 秒硬超时,SHA256 缓存 7 天 |

Tier 2 是**追加**,绝不替代 Tier 1。模型调用未开启/超时/出错/没凭据时,你依然会看到
完整的 Tier 1 注释。模型**只看到命令字符串本身**(绝不涉及 cwd、会话或 transcript)。

## 安装

Permission Lens 是一个 `PermissionRequest` hook。需要 `PATH` 里有
[`uv`](https://docs.astral.sh/uv/)(首次运行会自动拉取它唯一的依赖 PyYAML)。

### 方式 A — 本地开发(最快上手)

```bash
claude --plugin-dir /path/to/permission-lens
```

然后让 Claude 执行一条会触发权限弹框的命令。

### 方式 B — 手动写 `settings.json` hook

在 `~/.claude/settings.json` 里加入(用绝对路径),然后重启 Claude Code:

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --quiet /ABSOLUTE/PATH/permission-lens/hooks/permission_lens.py || true",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

结尾的 `|| true` 很关键:它保证即使启动器出错也不会以非零码退出、从而误**拒绝**权限
(`PermissionRequest` 上 exit 2 = deny)。

### 方式 C — 插件市场

把本仓库推到 GitHub 后,用户可以这样安装:

```
/plugin marketplace add <你的组织>/permission-lens
/plugin install permission-lens@permission-lens
```

(本仓库自身就是一个单插件市场,见
[`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)。)

## 配置

可选。创建 `~/.config/permission-lens/config.json`;每个 key 缺失或非法时都会逐项回落
默认值,所以坏配置不可能弄坏 hook。完整示例见
[`config.example.json`](config.example.json)。

| Key | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `lang` | `"en"` \| `"zh"` | `"en"` | 注释语言。 |
| `min_severity_to_annotate` | `"info"` \| `"low"` \| `"medium"` \| `"high"` | `"info"` | `"info"` 注释一切(含中立 ℹ️ 摘要);更高的值下,只有达到该级别的规则命中才注释,否则静默。 |
| `max_message_chars` | 80–9000 | 500 | 注释长度硬上限。 |
| `llm.enabled` | `true` \| `false` | `false` | 开启 Tier 2。必须是字面量 `true`。 |
| `llm.model` | 模型 id | `"claude-haiku-4-5"` | 任意 Messages API 模型。 |
| `llm.timeout_seconds` | 0.1–6.0 | 3.0 | API 调用的墙钟硬超时。 |
| `llm.api_key_env` / `llm.auth_token_env` | 环境变量名 | `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | 从哪里读你的凭据(见下)。 |
| `llm.cache_ttl_days` | 0–365 | 7 | 响应缓存 TTL;`0` 关闭缓存。 |

### 开启 Tier 2(用你自己的账户)

设 `"llm": { "enabled": true }`,并在环境里提供**你自己的**凭据——插件不携带任何 key,
也不经过任何中间服务器。解析顺序:

1. `ANTHROPIC_API_KEY` —— 作为 `x-api-key` 发送。
2. `ANTHROPIC_AUTH_TOKEN` —— OAuth bearer token(例如用 Anthropic CLI:
   `export ANTHROPIC_AUTH_TOKEN=$(ant auth print-credentials --access-token)`),
   作为 `Authorization: Bearer` 发送,并带上必需的 `oauth-2025-04-20` beta header。

两者都没有时,Tier 2 静默、你保留 Tier 1。注意:Claude Code 自身的 Pro/Max 登录凭据
**不会**被使用、也无法被使用——平台上没有把这些 API 调用记账到订阅的合规途径。

## 本地怎么测试

- **跑完整检查**(测试 + hook 冒烟 + 清单校验):

  ```bash
  scripts/check.sh
  ```

- **只跑测试套件**(160 个测试,全部离线):

  ```bash
  uv run --with pytest --with pyyaml python -m pytest tests/
  ```

- **手动喂一条命令给 hook**,看原始输出:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf \"$TMP\"/*"}}' \
    | uv run --quiet hooks/permission_lens.py
  ```

- **交互 / 桌面 / 配置的逐步验证**:见
  [`scripts/manual-test.md`](scripts/manual-test.md)。

## 设计原则

- **绝不当守门员。** 永不输出 `hookSpecificOutput`/`decision`。
- **永远 fail open。** 每条路径都只打印一个 JSON 对象并 exit 0——`PermissionRequest`
  上 exit 2 会 deny,所以任何内部错误都降级成静默的 `{}`,原生弹框照常显示(不带注释)。
- **Tier 1 离线、仅标准库**(PyYAML 除外),运行 <10ms。
- **数据留在本地。** Tier 2 只发送命令字符串,走 TLS,只用你自己的凭据。

MIT —— 见 [LICENSE](LICENSE)。schema 验证与设计记录见 [NOTES.md](NOTES.md)。
