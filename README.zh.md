# Approval Lens

[English](README.md) · **中文**

[安装](#安装) · [首次使用](#首次使用) · [模型说明](#模型说明可选)

**批准前，先看懂。**

即使可以给 agent 完全权限，用户或企业仍可能要求保留审批：普通操作自动通过，部分操作仍需确认，
或每一步都手动审批。
但弹窗和终端里的提示有时只给出命令、权限名称或笼统的理由，用户未必明白批准后会发生什么。

Approval Lens 用直白的语言解释待审批操作：它要做什么、影响哪些文件或服务、可能产生什么变化，
帮助用户决定批准还是拒绝。

审批说明支持 **6 种语言**：英语、简体中文、繁体中文、日语、西班牙语和法语。
[选择显示语言](#语言与提示范围)。

例如，你让 agent 制作启动盘，审批提示里出现这条命令（仅作说明）：

`sudo dd if=installer.img of=/dev/disk2 bs=4m`

Approval Lens 的解释可以是：

> 🔴 高危 · 这会把安装镜像写入磁盘 /dev/disk2，覆盖盘上已有的数据。请确认它是你要制作的启动盘；选错磁盘可能导致文件丢失，甚至系统无法启动。

## 当前支持

首个接入的是 Claude Code。Codex、Cursor 和 OpenCode 在计划中。

| Agent | 当前状态 |
| --- | --- |
| Claude Code | 已提供：Bash、WebFetch、Write、Edit |
| Codex | 计划接入 |
| Cursor | 计划接入 |
| OpenCode | 计划接入 |

当前首版只解释命中规则且达到阈值的操作。为更多已有审批提示补充解释，是后续接入的重点；
目前还不能覆盖每一次审批。

## 安装

以下步骤适用于已[安装 Claude Code 2.1.211 或更新版本](https://code.claude.com/docs/en/quickstart) 的 macOS 或 Linux 终端。
旧版本在 Auto 模式下可能跳过 hook 请求的确认，见 [Claude 的 hook 行为说明](https://code.claude.com/docs/en/hooks#pretooluse-decision-control)。

### 1. 安装 uv

如果 `uv --version` 已能运行，可跳过。否则使用 [uv 官方安装器](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

重新打开终端，确认两个命令均能显示版本：

```bash
claude --version
uv --version
```

### 2. 安装 Approval Lens

下载并解压[项目 ZIP](https://github.com/roctang2021/approval-lens/archive/refs/heads/main.zip)。
在解压后包含本 README 和 `hooks/` 的文件夹中打开终端，执行：

```bash
uv run --quiet hooks/approval_lens.py </dev/null >/dev/null
claude plugin marketplace add ./ --scope user
claude plugin install approval-lens@approval-lens --scope user
```

第一条命令会按需准备 Python 和 PyYAML，后两条命令安装插件，对当前用户的各个项目生效。
请保留原文件夹，供后续更新使用。
只需安装一次，以后照常运行 `claude` 即可。本地规则不需要模型 API key。

## 首次使用

1. 关闭正在运行的 Claude Code 会话，在你要工作的项目中重新运行 `claude`。
2. 输入 `/plugin`，打开 **Installed**，确认 Approval Lens 已启用。
3. 照常使用 Claude。操作命中高危规则时，Approval Lens 会在审批时提供说明。
   阅读后，通过 Claude 原有的按钮批准或拒绝操作。

默认语言为英文，默认只提示**高危**操作；普通操作可能没有额外提示。
修改中文显示见下方[语言与提示范围](#语言与提示范围)。
插件未出现或没有显示说明时，参阅[排查步骤](docs/configuration.zh.md#没有出现说明)。

## 模型说明（可选）

需要针对具体命令和目标的解释时，可开启模型接入。当前使用 Anthropic API key，费用计入 API 账户。

1. 创建配置文件夹：

   ```bash
   mkdir -p ~/.config/approval-lens
   ```

2. 用文本编辑器将 API key 单独保存为 `~/.config/approval-lens/api-key` 的一行，然后限制访问权限：

   ```bash
   chmod 600 ~/.config/approval-lens/api-key
   ```

3. 创建 `~/.config/approval-lens/config.json`，填入以下内容。如果文件已存在，将 `llm` 设置合并进去：

   ```json
   {
     "llm": {
       "enabled": true,
       "api_key_file": "~/.config/approval-lens/api-key"
     }
   }
   ```

之后命中的审批提示可以包含**操作说明**。没有密钥或请求失败时，仍显示本地规则说明。
将 `enabled` 改为 `false` 即可关闭。

模型会收到命令、URL 或文件路径。发送文件内容和用户请求需要分别开启，详见[配置与数据处理](docs/configuration.zh.md#开启模型说明)。

## 语言与提示范围

需要中文显示或包含中危操作时，创建或修改 `~/.config/approval-lens/config.json`。
以下设置可与 `llm` 并存：

```json
{
  "lang": "zh",
  "ask": { "min_severity": "medium" }
}
```

语言代码：英语（`en`）、简体中文（`zh`）、繁体中文（`zh-Hant`）、日语（`ja`）、西班牙语（`es`）、法语（`fr`）。设置在下一次检查时生效。
其他选项见[完整配置](docs/configuration.zh.md#配置项)。

## 检查范围

| Claude Code 操作 | 风险信号示例 |
| --- | --- |
| Bash | 下载后执行、递归删除、凭据路径、强制推送、发布包 |
| WebFetch | URL 中的凭据、疑似密钥参数、IP 或 localhost 目标 |
| Write / Edit | 敏感路径、启动脚本、Git 钩子、下载执行或 eval 文本 |

规则在本机确定风险等级。达到阈值时，适配器请求确认并附上说明，
因此原本自动批准的操作也可能增加一次确认。低于阈值时不返回决策，插件不返回 allow 或 deny。

## 使用边界

- 检查依赖规则；没有提示不代表操作安全。
- shell 分析器处理常见的包装命令、管道和替换表达式，不是完整的 shell 解释器，
  也不检查下载的代码。分步下载、再执行脚本的行为不在跟踪范围内。
- 文件内容规则只匹配文本，不能确认这些文本是否会执行。MultiEdit 和未列出的工具尚未覆盖。
- 最终审批流程由宿主控制。已识别的 Claude Code 无人值守会话默认不请求确认；
  hook 出错时由宿主继续按原有权限机制处理。
- 模型说明可能出错。过滤规则能识别部分批准建议和安全结论，不能保证事实准确。

## 查看状态与开发

```bash
uv run scripts/approval-lens-status.py   # 最近检查、当天计数和模型说明状态
./scripts/check.sh            # 测试、静态检查、hook 冒烟测试和语言文件
```

[配置](docs/configuration.zh.md) · [架构与接入计划](docs/architecture.md) ·
[更新与卸载](docs/configuration.zh.md#更新与卸载) ·
[贡献指南](CONTRIBUTING.md) · [更新记录](CHANGELOG.md) · [工程记录](NOTES.md)

MIT · [许可证](LICENSE)
