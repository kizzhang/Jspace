<p align="center">
  <img src="docs/assets/jspace-logo.png" alt="JSpace logo" width="280" />
</p>

<h1 align="center">JSpace</h1>

<p align="center"><strong>A local-first thinking workspace for the output before the output.</strong></p>

**JSpace 科研工作台** 把散落在 AI 对话、实验目录、论文与每日工作痕迹里的研究过程，整理成一层可搜索、可回溯的研究记忆。它关注的不只是最终产物，更是产物出现之前的东西：尚未写进论文的判断、失败实验留下的约束、调研形成的直觉，以及人与模型共同推演时产生的隐性知识。

**声明**：这个工作台是独立项目，并非 Anthropic 官方产品，也不代表 Anthropic 的背书。`JSpace` 这个名字承接相关研究语境，AI模型有一个 *workspace* 来思考信息；**JSpace 科研工作台** 则是实现专注于个人科研思考和发现过程的管理。希望你能够把项目的 *workspace memory* 最终通过 *unembedding* 解出顶刊顶会！

## 为什么需要它

研究最容易丢失的通常不是文件，而是文件之间的关系：为什么做这个实验、读某篇论文解决了什么疑问、哪次对话改变了方案、一个结论究竟由什么证据支持。JSpace 保留原始资料的位置，只建立一个可重建的本地索引，让这些关系重新可见。

```text
AI 对话 ─┐
实验记录 ├─> 本地索引 ─> 每日 TL;DR / 对话 / 实验 / 文献 ─> 可回溯的研究记忆
论文 PDF ┤
研究文档 ┘
```

## 当前能力

- **每日 TL;DR**：按“实验—调研—结果”组织当天进展，用平白语言交代做了什么、看了什么、得到什么；只有必要时保留公式。
- **对话 TL;DR**：为每个 Codex / Claude Code 研究会话生成摘要与关键词，同时保留逐条问答入口。
- **实验时间线**：扫描实验脚本、预注册、结果、settlement 与结论文件，辅助判断草稿、已配置、有结果或已结论状态。
- **文献库与阅读器**：按 DOI、arXiv、标题与 PDF 指纹去重；支持本地 PDF、公开原文入口、阅读状态和研究备注。
- **研究文本渲染**：本地渲染 Markdown、代码块与 KaTeX 公式；输入内容经 DOMPurify 清理。
- **本地搜索**：在对话、实验和论文之间统一检索，不要求把研究资料上传到第三方服务。

## 隐私模型

JSpace 默认只监听 `127.0.0.1`。原始对话、实验结果和 PDF 都是只读事实来源；工作台只写入自己的 `.data/` 索引和当日日报。

| 内容 | 默认行为 |
| --- | --- |
| 对话全文、实验结果、PDF | 留在本机，不复制进仓库，不被工作台改写 |
| SQLite 索引与个人备注 | 写入 `tools/research_workbench/.data/`，被 Git 忽略 |
| DOI / arXiv 元数据 | 需要时使用公开标识获取；不会发送对话或实验内容 |
| Web 服务 | 仅绑定本机回环地址，除非用户显式修改 `--host` |

> [!IMPORTANT]
> 不要把 `.data/`、对话 JSONL、实验结果目录或论文 PDF 提交到 Git。若机器启用了磁盘加密，JSpace 不会绕过或削弱系统权限；它只读取当前 Windows 用户本来就能访问的文件。

## 快速开始

要求：Windows PowerShell、Python 3.11+。运行时仅使用 Python 标准库；执行测试需要 `pytest`。

```powershell
git clone https://github.com/kizzhang/jspace-workbench.git
cd jspace-workbench

# 指向需要整理的研究目录
.\tools\research_workbench\launch.ps1 -Workspace "E:\path\to\your-research-workspace"
```

浏览器会打开 `http://127.0.0.1:7333/`。也可以通过环境变量固定研究目录：

```powershell
$env:JSPACE_WORKSPACE = "E:\path\to\your-research-workspace"
.\tools\research_workbench\launch.ps1
```

常用命令：

```powershell
# 后台启动，不自动打开浏览器
.\tools\research_workbench\launch.ps1 -Workspace "E:\research" -Background -NoBrowser

# 只更新本地索引与当日日报
.\tools\research_workbench\daily_sync.ps1 -Workspace "E:\research"

# 直接运行 Python 入口
python .\tools\research_workbench\app.py --workspace "E:\research" --port 7333
```

## JSpace 会读取什么

- 当前研究目录及其 Git worktree 中的实验脚本、文档、结果清单和论文；
- 当前用户本机保存的 Codex / Claude Code 会话，但只收录与所选研究目录相关的记录；
- `.data/literature.json` 中手工维护的文献线索；
- 已放入研究目录的 PDF，以及 DOI / arXiv 等公开文献标识。

文献种子示例：

```json
[
  {
    "doi": "10.0000/example",
    "arxiv_id": "2601.00001",
    "title": "Example Paper",
    "pdf_path": "papers/example.pdf",
    "status": "reading",
    "notes": "与当前假设的关系"
  }
]
```

也可以通过页面右上角的“添加文献”录入 DOI、arXiv ID、标题或本地 PDF 路径。相同 DOI、arXiv ID、PDF 指纹或规范化标题会合并到同一条记录。

## 数据与设计原则

1. **原始资料不搬家**：对话、结果和 PDF 始终是事实来源。
2. **摘要不是证据**：TL;DR 用来导航，结论仍可回到原会话、文件和论文核对。
3. **自动记录，人类定论**：自动状态和摘要降低整理成本，研究者的备注单独保存。
4. **合并而非静默丢弃**：重复文献更新同一记录，同时保留稳定身份。
5. **索引可重建**：删除 `.data/` 不会伤及原始研究资料，下次同步可以重新生成。

更完整的信息模型见 [`DESIGN.md`](./DESIGN.md)。

## 测试

```powershell
python -m pytest tests/test_research_workbench.py tests/test_research_workbench_ui.py -q
```

测试使用合成数据，不依赖或上传个人研究内容。

## 项目状态

JSpace 目前是面向个人研究工作流的早期版本，优先保证本地可用、资料可回溯和隐私边界清楚。接下来适合继续完善的方向包括 Zotero 同步、结论—证据图谱、实验运行采集和可移植导出。
