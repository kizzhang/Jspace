# JSpace 每日自动更新指南

本指南说明如何让 Codex 或其他 AI agent 每日更新 JSpace，以及如何用 Windows Task Scheduler / cron 获得更稳定的无人值守运行。

## 1. 先理解任务边界

JSpace 的每日更新不是让模型重新自由总结整个项目，而是让调度器执行一个确定性入口：

```powershell
.\tools\research_workbench\daily_sync.ps1 -Workspace "E:\path\to\research-workspace"
```

脚本负责扫描资料、更新本地索引并生成当日日报。Agent 的职责只有三项：

1. 在正确的研究目录运行脚本；
2. 检查退出码和同步结果；
3. 成功时报告，失败时在 `tools/research_workbench` 范围内只读诊断。

这种分工比“让 agent 自己寻找并改写所有资料”更稳定，也能确保原始对话、实验结果和 PDF 保持只读。

## 2. 选择运行方式

| 方式 | 适合场景 | 是否能访问本机资料 | 推荐度 |
| --- | --- | --- | --- |
| Codex 桌面端 Scheduled | 想要每日自动运行并在 Codex 中查看报告 | 可以；电脑和应用需保持运行 | 推荐 |
| Windows Task Scheduler 直接运行脚本 | 追求最低成本、最高确定性 | 可以；必须使用有权限的同一用户 | 最稳妥 |
| Windows Task Scheduler + `codex exec` | 需要 agent 自动验收和失败诊断 | 可以；需要 Codex CLI 登录有效 | 推荐给高级用户 |
| Web 端 Scheduled / 云端 agent | 资料已上传或来自连接器 | 不能直接访问本机目录 | 不适合本地 JSpace 索引 |
| 其他 agent CLI + 系统 cron | 已有支持非交互模式的 agent | 取决于 runner 的文件权限 | 可用 |

对于 JSpace，建议直接运行在**本地项目**，不要为每日任务创建临时 worktree。`.data/` 是被 Git 忽略的本地状态；临时 worktree 会让索引分散，无法形成连续的研究记忆。

## 3. 运行前检查

先在普通 PowerShell 中手动执行一次：

```powershell
$workspace = "E:\path\to\research-workspace"
Set-Location -LiteralPath $workspace
& .\tools\research_workbench\daily_sync.ps1 -Workspace $workspace
if ($LASTEXITCODE -ne 0) {
    throw "JSpace daily sync failed with exit code $LASTEXITCODE"
}
```

确认以下条件：

- 退出码为 `0`；
- `tools/research_workbench/.data/workbench.sqlite` 已创建或更新时间发生变化；
- 终端输出包含对话、实验、文献和日报统计；
- 刷新工作台后能看到当天的 TL;DR；
- 原始对话、实验结果和 PDF 的修改时间没有变化。

如果电脑使用 BitLocker、EFS 或其他本地加密，定时任务必须以**平时能够读取这些文件的同一 Windows 用户**运行。不要切换到 `SYSTEM`、服务账户或另一个用户，也不要尝试绕过加密。

## 4. Codex 桌面端 Scheduled（最方便）

Codex / ChatGPT 桌面端的 Scheduled 可以在本地项目目录中执行定时任务。需要满足：电脑开机、磁盘已解锁、桌面应用保持运行、所选项目路径仍然存在。

### 创建步骤

1. 在 Codex 桌面端打开研究项目。
2. 新建对话，粘贴[每日同步 Agent Prompt](./prompts/daily-sync-agent.md) 的内容，先手动运行一次。
3. 确认结果正确后，在该对话中要求：

   ```text
   把这项任务创建为独立的 Scheduled task，每天本地时间 23:30 运行。
   工作目录使用当前本地项目，直接在本地项目中运行，不创建 worktree。
   每次运行都使用保存的每日同步 prompt，并把结果放进 Scheduled。
   ```

4. 打开侧栏的 **Scheduled**，检查任务、时区、下一次运行时间和项目目录。
5. 权限使用 `workspace-write`。不要使用 `danger-full-access`；核心同步不需要它。
6. 点击 **Run now** 验证首轮运行。连续查看前 2–3 次结果，再决定是否调整时间或提示词。

如果需要自定义 RRULE，每天 23:30 可表示为：

```text
RRULE:FREQ=DAILY;BYHOUR=23;BYMINUTE=30
```

### 推荐保存的任务指令

不要只写“每天更新一下 JSpace”。任务必须明确入口、成功标准和禁止项。仓库已经提供完整版本：[每日同步 Agent Prompt](./prompts/daily-sync-agent.md)。

### Codex Scheduled 的注意事项

- Codex CLI 和 IDE 扩展不提供 Scheduled 管理界面；创建和管理任务要使用桌面端或 ChatGPT Web。
- Web 端任务不能直接读取电脑里的本地目录；本项目必须使用桌面端的本地项目任务。
- 独立 Scheduled task 每次从保存的 prompt 开始，适合每日同步；只有需要持续沿用对话上下文时才放在既有对话中。
- 定时任务无人值守运行，应使用最小权限；组织策略不允许无审批运行时，任务可能回退到所选权限模式的审批行为。
- 如果任务没有执行，先检查电脑是否休眠、应用是否退出、项目目录是否离线，以及 Scheduled 中是否显示权限请求。

官方参考：[Scheduled tasks](https://learn.chatgpt.com/docs/automations.md)、[Sandboxing](https://learn.chatgpt.com/docs/sandboxing)。

## 5. Windows Task Scheduler 直接运行（最稳妥）

每日同步本身不要求模型参与。若重点是稳定更新索引，最可靠的方式是让 Windows 直接执行脚本；需要解释失败时，再把日志交给 agent。

### 图形界面配置

在“任务计划程序”中选择“创建任务”，建议使用：

| 配置项 | 值 |
| --- | --- |
| 名称 | `JSpace Daily Sync` |
| 安全选项 | 使用当前 Windows 用户；加密机器建议“仅当用户登录时运行” |
| 触发器 | 每天 23:30；启用“错过后尽快运行” |
| 程序 | `pwsh.exe` 的绝对路径 |
| 参数 | 见下方示例 |
| 起始于 | 研究工作区绝对路径 |
| 多实例 | 已有实例运行时不启动新实例 |

参数示例：

```text
-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "E:\path\to\research-workspace\tools\research_workbench\daily_sync.ps1" -Workspace "E:\path\to\research-workspace"
```

### 用 PowerShell 创建任务

以下命令只需要执行一次。先替换 `$workspace`：

```powershell
$taskName = "JSpace Daily Sync"
$workspace = "E:\path\to\research-workspace"
$script = Join-Path $workspace "tools\research_workbench\daily_sync.ps1"
$pwsh = (Get-Command pwsh.exe).Source
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$arguments = @(
    "-NoLogo"
    "-NoProfile"
    "-NonInteractive"
    "-ExecutionPolicy Bypass"
    "-File `"$script`""
    "-Workspace `"$workspace`""
) -join " "

$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument $arguments `
    -WorkingDirectory $workspace

$trigger = New-ScheduledTaskTrigger -Daily -At 23:30
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Update the local JSpace index and daily brief"
```

立即测试并查看结果：

```powershell
Start-ScheduledTask -TaskName "JSpace Daily Sync"
Start-Sleep -Seconds 5
Get-ScheduledTaskInfo -TaskName "JSpace Daily Sync" |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
```

`LastTaskResult = 0` 表示任务进程成功退出。还应打开工作台确认当天日报，因为“进程成功”不等于“数据源中一定有新内容”。

## 6. Windows Task Scheduler + Codex CLI

当你希望 agent 每天运行脚本、解释结果并在失败时诊断，可让 Task Scheduler 调用 Codex 的非交互模式 `codex exec`。

先确认 Codex CLI 已登录，并手动测试：

```powershell
$workspace = "E:\path\to\research-workspace"
$prompt = Get-Content `
    -LiteralPath ".\docs\prompts\daily-sync-agent.md" `
    -Raw

$prompt | codex exec `
    --cd $workspace `
    --sandbox workspace-write `
    --ephemeral `
    -
```

关键参数：

- `--cd` / `-C`：把 agent 的工作目录固定到研究项目；
- `--sandbox workspace-write`：允许更新工作台本地索引，但不授予整台机器的无限权限；
- `--ephemeral`：不保留这次 CLI 会话的 rollout 文件；JSpace 自己的日报和索引仍会保留；
- `-`：从标准输入读取完整 prompt；
- `--json`：可选，输出 JSONL 事件，方便监控系统解析成功或失败。

在 Task Scheduler 中，可以把“程序”设置为 `pwsh.exe`，让参数调用一段受版本控制的 wrapper；不要把多行 prompt、API key 或访问令牌直接塞进任务参数。若使用 API key，只把 `CODEX_API_KEY` 暂时暴露给 `codex exec` 进程，不要设为整个任务或整个构建环境的全局变量。

Codex 官方将 `codex exec` 定位为 CI 和 scheduled jobs 的非交互入口，并建议新脚本显式使用 `--sandbox workspace-write`，不要使用已经弃用的 `--full-auto`。详见：[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode.md) 和 [`codex exec` 参数](https://learn.chatgpt.com/docs/developer-commands?surface=cli#cli-codex-exec)。

## 7. 其他 AI Agent 或 cron

任何支持非交互 CLI 的 agent 都可以复用同一流程：

```text
系统调度器
  -> 以同一系统用户启动 agent CLI
  -> 固定 cwd 为研究工作区
  -> 传入 DAILY_SYNC_AGENT_PROMPT.md
  -> agent 调用 daily_sync.ps1
  -> 以 agent/脚本退出码标记成功或失败
  -> 保存最终报告，失败时提醒用户
```

不要猜测不同 agent 的 CLI 参数。查阅该工具当前版本的官方文档，并寻找以下能力：

- non-interactive / print 模式；
- 指定 working directory；
- 限制文件写入范围；
- 禁止交互审批或为命令建立 allowlist；
- 输出最终消息或结构化 JSON；
- 明确的进程退出码。

通用伪命令：

```text
<agent-cli> \
  --non-interactive \
  --cwd <research-workspace> \
  --permission workspace-write \
  --prompt-file tools/research_workbench/DAILY_SYNC_AGENT_PROMPT.md
```

在 Linux/macOS runner 上，可让 cron 调用实际 agent wrapper：

```cron
30 23 * * * cd /absolute/path/to/research-workspace && /absolute/path/to/agent-wrapper >> tools/research_workbench/.data/agent-sync.log 2>&1
```

JSpace 当前的本地对话发现逻辑以桌面研究环境为中心；云端 runner 无法自动看到本机 Codex / Claude 会话、加密盘或本地 PDF。若使用云端 agent，必须先设计明确、安全的数据同步层，不能把整个研究目录直接上传。

## 8. 成功标准与告警

一次运行只有同时满足以下条件才算成功：

1. `daily_sync.ps1` 进程退出码为 `0`；
2. 本地索引可打开，没有 SQLite 错误；
3. 脚本输出了同步统计；
4. 当日日报存在，即使当天没有新实验也应给出明确状态；
5. 原始资料没有被修改；
6. 没有启动实验、提交 Git 或上传私有文件。

建议保存以下最小运行记录：

```text
started_at
finished_at
workspace
exit_code
conversation_count
experiment_count
paper_count
daily_brief_created
diagnostic_summary
```

失败时不要无限重试。推荐最多自动重试一次，仅限瞬时文件锁或网络错误；权限、加密、数据库损坏和脚本异常应直接报告。

## 9. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| Codex Scheduled 完全没运行 | 电脑是否睡眠、桌面应用是否退出、任务是否暂停 |
| Agent 说找不到项目 | `--cd` / Scheduled 项目目录是否指向真正的研究工作区 |
| worktree 中每天都是新索引 | 改为本地项目运行；不要把 `.data/` 放在临时 worktree |
| 任务显示成功但没有新对话 | 会话是否真的关联到该 workspace；路径是否改变 |
| `Access denied` / 解密失败 | 任务是否使用同一 Windows 用户、磁盘是否已解锁 |
| `pwsh.exe` 找不到 | 用 `(Get-Command pwsh.exe).Source` 写入绝对路径 |
| 两次任务互相锁住数据库 | 设置 `MultipleInstances IgnoreNew`，不要重叠运行 |
| Web 端 agent 看不到本地资料 | Web Scheduled 不直接访问本机目录；改用桌面端或本地 runner |
| Agent 想修改工作台源码 | Prompt 中保持“失败只读诊断；未经授权不修复” |

## 10. JSpace 的推荐默认配置

- 时间：每天本地时间 23:30；
- 运行位置：本地研究项目；
- 执行入口：`daily_sync.ps1 -Workspace <workspace>`；
- Agent：Codex Scheduled 或 `codex exec`；
- 权限：`workspace-write`，不使用 full access；
- 并发：同一时间只允许一个同步实例；
- 身份：能够访问加密研究资料的同一系统用户；
- 成功报告：同步统计 + 日报状态 + 隐私边界确认；
- 失败行为：停止、只读诊断、报告，不启动实验，不擅自修复。
