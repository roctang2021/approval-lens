# 配置 — Claude Code 接入

[English](configuration.md) · **中文** · [README](../README.zh.md)

创建 `~/.config/approval-lens/config.json`。缺失或类型无效的设置使用各自的默认值，
数值限制在支持范围内。完整结构见 [config.example.json](../config.example.json)。

早期本地预览使用 Permission Lens 名称。如果用过旧版，请按 Approval Lens 名称重新安装，
将需要保留的设置复制到 `~/.config/approval-lens/config.json`，并按需调整密钥文件路径。

## 配置项

| 配置项 | 默认值 | 可选值 / 作用 |
| --- | --- | --- |
| `lang` | `en` | `en`、`zh`、`zh-Hant`、`ja`、`es`、`fr`；影响弹窗、模型语言和状态输出 |
| `ask.min_severity` | `high` | `low`、`medium`、`high`；达到该等级时请求确认 |
| `ask.non_interactive` | `silent` | `silent` 或 `ask`；无人应答时请求确认可能导致工具调用失败 |
| `max_message_chars` | `500` | 80–9000 字符 |
| `llm.enabled` | `false` | 只有布尔值 `true` 才开启模型说明 |
| `llm.model` | `claude-sonnet-5` | 发送给 Anthropic Messages API 的模型 ID；请选择账户可用的模型 |
| `llm.timeout_seconds` | `5.0` | 0.1–6.0 秒；超时后使用规则说明 |
| `llm.api_key_env` | `ANTHROPIC_API_KEY` | 保存 API key 的环境变量名 |
| `llm.api_key_file` | 空 | 可选密钥文件；环境变量中没有密钥时使用 |
| `llm.cache_ttl_days` | `7` | 0–365 天；0 关闭缓存读取和写入 |
| `llm.send_file_content` | `false` | 额外发送 Write 的 content 或 Edit 的 new_string |
| `llm.send_task_context` | `false` | 额外发送 Claude Code transcript 中最近可用的用户请求，最多 400 字符 |

适配器通过 `CLAUDE_CODE_ENTRYPOINT` 识别已知的无人值守入口：
`sdk-cli`、`sdk-py`、`sdk-ts`。缺失或未知的值按交互会话处理。

## 开启模型说明

模型将当前操作解释成便于审批的文字。若希望解释具体命令和目标，建议开启：

```json
{
  "llm": {
    "enabled": true,
    "api_key_file": "~/.config/approval-lens/api-key"
  }
}
```

将自己的 API key 单独写在文件的一行中，并用 `chmod 600` 限制访问权限。
环境变量优先于文件。GUI 应用无法读取 shell 环境变量时，可使用密钥文件。
当前接入只使用 API key，不复用 coding agent 的订阅登录。

需要补充“这与我的任务有什么关系”时，可在 `llm` 中单独设置
`"send_task_context": true`；这会发送最近可用的用户请求。若要解释文件修改内容，
还需单独设置 `"send_file_content": true`，否则模型只收到文件路径。

当前只有命中规则且达到确认阈值的操作才会调用模型。开启模型不会扩展审批覆盖范围。
没有密钥、API 出错或超时时，继续显示规则说明。

## 数据处理

- 本地规则检查命令、URL、文件路径和传入的新内容。
- 模型说明会将命令、URL 或路径发送给 Anthropic；这些文本本身可能含有凭据。
  文件内容和用户请求需要单独开启，cwd 和会话 ID 不会被附加到请求中。
- 模型回复保存在 `~/.cache/approval-lens/llm/`。文件名由输入和提示词的哈希生成，
  回复正文可能含有输入中的细节。使用缓存时会将目录限制为仅所有者可访问，新回复文件仅所有者可读写。
  修改提示词会改变缓存键。`cache_ttl_days` 设为 0 会保留旧文件；删除该 `llm/` 目录可清空已保存的回复。
- `heartbeat.json` 保存时间、版本、工具名、计数、风险等级和处理结果，
  不保存命令正文、URL 或文件路径。
- `APPROVAL_LENS_DEBUG=1` 开启本地诊断日志，可能包含路径和错误细节，分享前请检查内容。

测试时可用 `APPROVAL_LENS_CONFIG` 指定配置路径，用 `APPROVAL_LENS_CACHE_DIR` 指定缓存目录。

## 手动安装 hook

仅在没有通过插件管理器安装、也没有使用 `--plugin-dir` 加载时，采用[英文配置页的 settings.json 示例](configuration.md#manual-hook-installation)。
将示例合并到 `~/.claude/settings.json`，替换绝对路径并重启 Claude Code。
只配置一次，避免插件和手动 hook 重复执行。

示例中的 PATH 回退用于查找 uv；`|| true` 防止启动器错误向 Claude Code 返回阻断退出码。

## 更新与卸载

通过 [README 的文件夹方式](../README.zh.md#安装)安装后，将原文件夹内容更新为新版本，再运行：

```bash
claude plugin marketplace update approval-lens
claude plugin update approval-lens@approval-lens --scope user
```

重新启动 Claude Code 会话以加载更新。请保留注册时的文件夹位置，方便市场找到新版本。

不再使用时，运行：

```bash
claude plugin uninstall approval-lens@approval-lens --scope user
```

然后重新启动会话。Approval Lens 配置和密钥文件仍会保留；不再需要时可自行删除。
安装范围和管理方式遵循 [Claude Code 插件流程](https://code.claude.com/docs/en/discover-plugins)。

## 本地开发预览

在仓库根目录运行：

```bash
claude --plugin-dir "$PWD"
```

这种方式只对本次启动生效，之后预览需再次带上参数。同一会话中只加载已安装副本或工作副本中的一份。
直接检查 hook 输出或验证真实弹窗，参阅[开发检查清单](../scripts/manual-test.md)。

## 没有出现说明

运行 `claude plugin list`，确认 `approval-lens@approval-lens` 已启用。
没有列出时，从原项目文件夹重新执行[安装步骤](../README.zh.md#安装)；已禁用时，在 `/plugin` 中启用并重新启动会话。
如果企业策略限制自定义市场，请由管理员批准或分发插件。

在新终端运行 `uv --version`；找不到 uv 时先安装，再重启 Claude Code。
然后在原项目文件夹运行 `uv run scripts/approval-lens-status.py`，检查调用记录、风险等级和运行版本。
低于阈值的操作、已识别的无人值守会话通常没有提示。如果没有检查记录，确认插件已加载且 uv 能启动。
运行版本与仓库版本不同时，按安装方式更新插件或重新加载本地插件会话。

弹窗行为的验证步骤见[真实会话检查清单](../scripts/manual-test.md)。
