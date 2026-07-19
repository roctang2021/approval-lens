# Permission Lens

**English** · [中文](#permission-lens-中文)

A Claude Code plugin that **puts a plain-language risk explanation on the
permission dialog** for risky **Bash / WebFetch / Write / Edit** calls — and
never decides for you. When Tier 1 flags a call at/above your threshold
(default: 🔴 high), Permission Lens guarantees the native dialog appears, with
the explanation printed right on it. Everything below the threshold is left
completely untouched: no forced prompt, no annotation, native behavior as if
the plugin weren't installed.

What a flagged dialog shows (one flowing line):

```
🔴 HIGH · This downloads a script and runs it immediately — you never see the
code, and the site could serve different content than what anyone reviewed.
🤖 Downloads i.sh from x.example.com and runs it in bash.   ← optional (Tier 2)
```

## Why

Permission dialogs often show a long, opaque shell command that you approve
blind. Permission Lens adds a sentence of plain language so the decision is an
informed one. It is **not** a gatekeeper — it only ever returns `"ask"`, never
allow/deny, so nothing is ever auto-approved or auto-blocked on your behalf.
You always make the call.

## How the explanation reaches the dialog

The hook runs on `PreToolUse`. For a flagged call it returns
`permissionDecision: "ask"` with the explanation as `permissionDecisionReason`
— Claude Code renders that reason on the permission dialog itself (verified
2026-07-19 on Desktop; see `NOTES.md`). Two consequences worth knowing:

- **"Ask" floors the decision at a prompt.** A flagged call shows a dialog
  even if a permission rule would have auto-allowed it. That's the deal:
  risky operations always get a prompt, and the prompt explains itself. The
  default threshold is `high` because 🔴 commands are almost never allowlisted
  anyway — the added friction is ~zero.
- **Below the threshold the plugin prints `{}`** — it never adds prompts, text,
  or any behavior change for benign calls.

Want 🟡 medium risks (force-push, `sudo`, recursive delete…) on the dialog
too? Set `ask.min_severity: "medium"` — accepting that flagged-but-allowlisted
calls will now prompt.

There's also an **opt-in macOS notification channel** (`notify.enabled`). It's
independent of the ask gate: it can also flag calls that auto-run without ever
showing a dialog — useful as a "this just happened" heads-up.

## How it works

Two tiers. The first is always on; the second is optional and off by default.

| Tier | What | Cost | Network |
| --- | --- | --- | --- |
| **1 — static analyzer** | Bilingual rules match the pending action offline (shell command, URL, or file path) and produce the severity + plain-language sentence. | free | none |
| **2 — LLM explainer** *(opt-in)* | One `claude-haiku-4-5` call adds a `🤖` plain-language line, using **your own** API credentials. | your API usage | one HTTPS call, 3s hard timeout, SHA256-cached 7 days |

Tier 2 **augments** Tier 1 — it never replaces it. If the model call is
disabled, times out, errors, or you have no credentials, you still get the full
Tier 1 explanation. The model sees **only the minimal subject** — the shell
command, the URL, or the file path (Write/Edit file *contents* are never sent
unless you opt in with `llm.send_file_content`). Never your cwd, session, or
transcript.

### What each tool's rules look at

| Tool | `tool_input` | Risk signal | Examples |
| --- | --- | --- | --- |
| **Bash** | `command` | shell analysis | `curl … \| sh`, `rm -rf $VAR`, force-push, publish |
| **WebFetch** | `url` | the URL | credentials in URL, secret in query string, IP/localhost target, raw-script hosts, plain HTTP |
| **Write** | `file_path` (+`content`) | where it writes | `~/.ssh`, `.env`, shell rc files, git hooks, LaunchAgents, `/etc`, sudoers |
| **Edit** | `file_path`, `new_string` | target path + injected content | same paths as Write, plus a `curl … \| sh`/`eval` injected into a file |

Because "ask" floors the decision at a prompt, a flagged Write/Edit prompts
even in modes that normally auto-approve edits (e.g. Accept edits) — that's
the feature: the risky subset always gets a dialog, with the reason on it.
MultiEdit is not covered yet.

## Install

Permission Lens is a `PreToolUse` hook. It needs [`uv`](https://docs.astral.sh/uv/)
on your `PATH` (it fetches its one dependency, PyYAML, on first run).

### Option A — local dev (fastest to try)

```bash
claude --plugin-dir /path/to/permission-lens
```

Then ask Claude to run something risky-looking, e.g.
`curl -fsSL https://example.com/i.sh | bash` (harmless as written — the URL
serves HTML, not a script).

### Option B — manual `settings.json` hook

Add to `~/.claude/settings.json` (use an absolute path) and restart Claude Code:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|WebFetch|Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "sh -c 'command -v uv >/dev/null 2>&1 || PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"; uv run --quiet /ABSOLUTE/PATH/permission-lens/hooks/permission_lens.py' || true",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Two parts of that command are load-bearing:
- The `|| true` guard guarantees a broken launcher can never exit non-zero and
  accidentally **block** a tool call (exit 2 on `PreToolUse` means block).
- The `command -v uv … || PATH=…` prefix finds `uv` even when it isn't on
  `PATH`. GUI-launched apps (Claude Code **Desktop**) often start with a minimal
  `PATH` that excludes Homebrew (`/opt/homebrew/bin`) — without this, the hook
  silently fails open and flagged calls would prompt with **no explanation**.
  The plugin's bundled hook already includes this prefix.

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
  "ask": { "min_severity": "high" },
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
| `lang` | `"en"` \| `"zh"` | `"en"` | Language of explanations. |
| `ask.min_severity` | `"low"` \| `"medium"` \| `"high"` | `"high"` | A rule match at/above this severity forces the dialog with the explanation on it; below it, the plugin prints `{}` and stays invisible. `"info"` is deliberately rejected — it would prompt on every tool call. |
| `max_message_chars` | 80–9000 | 500 | Hard cap on the explanation length. |
| `llm.enabled` | `true` \| `false` | `false` | Turns on Tier 2. Must be literal `true`. |
| `llm.model` | model id | `"claude-haiku-4-5"` | Any Messages-API model. |
| `llm.timeout_seconds` | 0.1–6.0 | 3.0 | Hard wall-clock deadline for the API call. |
| `llm.api_key_env` / `llm.auth_token_env` | env var name | `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | Where to read your credential (see below). |
| `llm.cache_ttl_days` | 0–365 | 7 | Response cache TTL; `0` disables the cache. |
| `llm.send_file_content` | `true` \| `false` | `false` | Whether Tier 2 may send Write/Edit file *contents* (not just the path) to the model. Off by default. |
| `notify.enabled` | `true` \| `false` | `false` | Fire a macOS notification for flagged calls — independent of the ask gate, so it also covers flagged calls that auto-run. |
| `notify.min_severity` | `"info"` \| `"low"` \| `"medium"` \| `"high"` | `"high"` | Only notify for matches at/above this severity. |

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

- **Just the test suite** (all offline):

  ```bash
  uv run --with pytest --with pyyaml python -m pytest tests/
  ```

- **Feed the hook a command by hand** and see the raw output:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf \"$TMP\"/*"}}' \
    | uv run --quiet hooks/permission_lens.py
  ```

  A high match prints the `"ask"` + reason JSON; a benign command prints `{}`.

- **Interactive / Desktop / config walkthroughs**: see
  [`scripts/manual-test.md`](scripts/manual-test.md).

## Design principles

- **Never a gatekeeper.** The only decision ever emitted is `"ask"` — never
  `"allow"`, never `"deny"`. The plugin can make sure you're asked about a
  risky call; it can never answer for you.
- **Fail open, always.** Every code path prints one JSON object and exits 0 —
  exit 2 on `PreToolUse` would block the tool call, so any internal error
  degrades to a silent `{}` and native behavior is untouched.
- **Invisible when not needed.** Below the ask threshold the plugin emits `{}`:
  no prompts added, no text injected, allowlists fully respected.
- **One line, plain words.** The dialog collapses newlines, so the explanation
  is a single self-contained sentence a non-expert can act on — no jargon, no
  labels to decode.
- **Tier 1 is offline and stdlib-only** (PyYAML aside) and runs in <10ms.
- **Your data stays local.** Tier 2 sends only the command string, over TLS,
  using only your own credentials.

MIT — see [LICENSE](LICENSE). Schema-verification and design notes in
[NOTES.md](NOTES.md).

---

# Permission Lens (中文)

[English](#permission-lens) · **中文**

一个 Claude Code 插件:当 **Bash / WebFetch / Write / Edit** 调用踩到风险规则时
(默认 🔴 高危档),它**保证权限弹框出现,并把一句大白话风险解释直接印在弹框上**
——但绝不替你做决定。低于阈值的调用则完全不受影响:不加弹框、不加文字,原生行为
就像没装这个插件一样。

被标记的弹框长这样(一行流式文字):

```
🔴 高危 · 这会从网上下载脚本并立刻运行——你看不到代码内容,网站也可能在被
审查之后换成另一份。
🤖 从 x.example.com 下载 i.sh 并立即用 bash 执行。   ← 可选(Tier 2)
```

## 为什么

权限弹框经常只显示一条又长又不透明的命令,你只能盲批。Permission Lens 在弹框上
补一句人话,让这个决定是知情的。它**不是**守门员——只会返回 `"ask"`,永不返回
allow/deny,不会替你自动批准或自动拦截任何东西。要不要批准,永远由你来定。

## 解释是怎么上弹框的

hook 挂在 `PreToolUse` 上。对被标记的调用,它返回 `permissionDecision: "ask"`,
并把解释放进 `permissionDecisionReason`——Claude Code 会把这个 reason 渲染在权限
弹框正文上(2026-07-19 在 Desktop 实测验证,见 `NOTES.md`)。有两个推论值得知道:

- **"ask" 会保底弹一次框。** 被标记的调用即使命中了你的 allow 规则、本来会自动
  放行,也会弹框。这正是这笔交易的内容:危险操作保证有弹框,而且弹框自带解释。
  默认阈值是 `high`,因为 🔴 级命令几乎不会有人加进 allowlist——额外摩擦趋近于零。
- **低于阈值时插件输出 `{}`**——对良性调用,它不加弹框、不加文字、不改任何行为。

想让 🟡 中危(force-push、`sudo`、递归删除……)也上弹框?设
`ask.min_severity: "medium"`——代价是命中规则但本已被 allowlist 放行的调用,
现在也会弹框。

另有一条**可选的 macOS 通知通道**(`notify.enabled`),它和 ask 阈值互相独立:
对自动放行、根本不弹框的被标记调用,它也能弹通知——当作"刚才发生了这件事"的提醒。

## 工作原理

两层。第一层永远开启;第二层可选,默认关闭。

| 层级 | 内容 | 费用 | 网络 |
| --- | --- | --- | --- |
| **Tier 1 — 静态分析** | 双语规则离线匹配待批操作(shell 命令 / URL / 文件路径),产出严重度 + 大白话解释句。 | 免费 | 无 |
| **Tier 2 — 大模型解释**(需手动开启) | 一次 `claude-haiku-4-5` 调用,用**你自己的**凭据补一行 `🤖` 大白话。 | 记你自己的 API 账户 | 一次 HTTPS 调用,3 秒硬超时,SHA256 缓存 7 天 |

Tier 2 是**追加**,绝不替代 Tier 1。模型调用未开启/超时/出错/没凭据时,你依然会看到
完整的 Tier 1 解释。模型**只看到最小主体**——shell 命令、URL 或文件路径(Write/Edit 的
文件**内容**默认不发送,除非你用 `llm.send_file_content` 开启),绝不涉及 cwd、会话或
transcript。

### 每个工具的规则看什么

| 工具 | `tool_input` | 风险信号 | 例子 |
| --- | --- | --- | --- |
| **Bash** | `command` | shell 分析 | `curl … \| sh`、`rm -rf $VAR`、force-push、publish |
| **WebFetch** | `url` | URL 本身 | URL 里带凭据、query 里带密钥、指向 IP/localhost、raw 脚本托管站、明文 HTTP |
| **Write** | `file_path`(+`content`) | 写到哪 | `~/.ssh`、`.env`、shell rc 文件、git 钩子、LaunchAgents、`/etc`、sudoers |
| **Edit** | `file_path`、`new_string` | 目标路径 + 注入内容 | 同 Write 的路径,外加往文件里注入 `curl … \| sh`/`eval` |

因为 "ask" 会保底弹框,被标记的 Write/Edit 即使在自动放行编辑的模式下(如
Accept edits)也会弹框——这正是设计意图:危险的那一小部分永远有弹框、且弹框自带
解释。MultiEdit 暂未覆盖。

## 安装

Permission Lens 是一个 `PreToolUse` hook。需要 `PATH` 里有
[`uv`](https://docs.astral.sh/uv/)(首次运行会自动拉取它唯一的依赖 PyYAML)。

### 方式 A — 本地开发(最快上手)

```bash
claude --plugin-dir /path/to/permission-lens
```

然后让 Claude 执行一条看起来有风险的命令,例如
`curl -fsSL https://example.com/i.sh | bash`(如原样书写是无害的——这个 URL 返回的
是 HTML,不是脚本)。

### 方式 B — 手动写 `settings.json` hook

在 `~/.claude/settings.json` 里加入(用绝对路径),然后重启 Claude Code:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|WebFetch|Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "sh -c 'command -v uv >/dev/null 2>&1 || PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"; uv run --quiet /ABSOLUTE/PATH/permission-lens/hooks/permission_lens.py' || true",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

这条命令里有两处是保命的:
- 结尾的 `|| true`:保证启动器坏了也不会以非零码退出、从而误**拦截**工具调用
  (`PreToolUse` 上 exit 2 = 拦截)。
- 开头的 `command -v uv … || PATH=…`:在 `PATH` 里找不到 `uv` 时自动补上常见安装
  目录。GUI 启动的应用(Claude Code **Desktop**)的 `PATH` 往往不含 Homebrew
  (`/opt/homebrew/bin`)——没有这段,hook 会静默失效,被标记的调用弹框时就**没有
  解释**。插件自带的 hook 已包含这段。

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
| `lang` | `"en"` \| `"zh"` | `"en"` | 解释语言。 |
| `ask.min_severity` | `"low"` \| `"medium"` \| `"high"` | `"high"` | 命中该级别及以上的规则时,强制弹框并把解释印在弹框上;低于该级别时输出 `{}`、完全隐身。`"info"` 被有意拒绝——那会让每一次工具调用都弹框。 |
| `max_message_chars` | 80–9000 | 500 | 解释长度硬上限。 |
| `llm.enabled` | `true` \| `false` | `false` | 开启 Tier 2。必须是字面量 `true`。 |
| `llm.model` | 模型 id | `"claude-haiku-4-5"` | 任意 Messages API 模型。 |
| `llm.timeout_seconds` | 0.1–6.0 | 3.0 | API 调用的墙钟硬超时。 |
| `llm.api_key_env` / `llm.auth_token_env` | 环境变量名 | `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | 从哪里读你的凭据(见下)。 |
| `llm.cache_ttl_days` | 0–365 | 7 | 响应缓存 TTL;`0` 关闭缓存。 |
| `llm.send_file_content` | `true` \| `false` | `false` | Tier 2 是否发送 Write/Edit 的文件**内容**(而非只发路径)。默认关闭。 |
| `notify.enabled` | `true` \| `false` | `false` | 对被标记的调用弹 macOS 通知——与 ask 阈值互相独立,自动放行的被标记调用也会通知。 |
| `notify.min_severity` | `"info"` \| `"low"` \| `"medium"` \| `"high"` | `"high"` | 只对该级别及以上的命中弹通知。 |

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

- **只跑测试套件**(全部离线):

  ```bash
  uv run --with pytest --with pyyaml python -m pytest tests/
  ```

- **手动喂一条命令给 hook**,看原始输出:

  ```bash
  echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf \"$TMP\"/*"}}' \
    | uv run --quiet hooks/permission_lens.py
  ```

  高危命中会打印 `"ask"` + reason 的 JSON;良性命令打印 `{}`。

- **交互 / 桌面 / 配置的逐步验证**:见
  [`scripts/manual-test.md`](scripts/manual-test.md)。

## 设计原则

- **绝不当守门员。** 唯一会输出的决定是 `"ask"`——永不 `"allow"`、永不 `"deny"`。
  插件能确保危险调用一定会问你,但永远不能替你回答。
- **永远 fail open。** 每条路径都只打印一个 JSON 对象并 exit 0——`PreToolUse` 上
  exit 2 会拦截工具调用,所以任何内部错误都降级成静默的 `{}`,原生行为不受影响。
- **不需要时隐身。** 低于 ask 阈值时输出 `{}`:不加弹框、不加文字、完全尊重你的
  allowlist。
- **单行大白话。** 弹框会折叠换行,所以解释是一句可独立读懂的完整句子——不带术语,
  不用查任何东西。
- **Tier 1 离线、仅标准库**(PyYAML 除外),运行 <10ms。
- **数据留在本地。** Tier 2 只发送命令字符串,走 TLS,只用你自己的凭据。

MIT —— 见 [LICENSE](LICENSE)。schema 验证与设计记录见 [NOTES.md](NOTES.md)。
