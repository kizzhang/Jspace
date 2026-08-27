import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "research_workbench"))

from workbench import (  # noqa: E402
    ResearchIndex,
    conversation_summary,
    conversation_tldr,
    experiment_details,
    extract_keywords,
    normalize_arxiv,
    normalize_doi,
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def test_identifier_normalization():
    assert normalize_doi("https://doi.org/10.1038/S41586-024-00001-2.") == "10.1038/s41586-024-00001-2"
    assert normalize_arxiv("https://arxiv.org/abs/2405.08200v2") == "2405.08200"


def test_historical_research_papers_and_nested_pdfs_are_backfilled(tmp_path: Path):
    workspace = tmp_path / "JSpace"
    literature = workspace / "docs" / "literature"
    literature.mkdir(parents=True)
    (workspace / "docs" / "related_work.md").write_text(
        "# Related work\n\n"
        "- Dongre et al. 2026, [When Attention Closes](https://arxiv.org/pdf/2605.12922)\n"
        "- [When Attention Closes](https://arxiv.org/abs/2605.12922v2)\n"
        "- [State Tracking Under Interventions](https://openreview.net/pdf?id=paper123)\n",
        encoding="utf-8",
    )
    pdf = literature / "dongre_2026_when_attention_closes.pdf"
    pdf.write_bytes(b"%PDF-1.4\nlocal fixture")

    index = ResearchIndex(workspace, state_dir=tmp_path / "state", user_home=tmp_path / "home")
    try:
        assert index.sync_researched_papers() == 2
        assert index.sync_pdf_inbox() == 2
        papers = index.list_papers()
        assert len(papers) == 2
        arxiv = next(item for item in papers if item["arxiv_id"] == "2605.12922")
        assert arxiv["title"] == "When Attention Closes"
        assert arxiv["status"] == "read"
        assert arxiv["pdf_path"] == str(pdf.resolve())
        assert any(item["source_url"] == "https://openreview.net/forum?id=paper123" for item in papers)
    finally:
        index.close()


def test_conversation_tldr_and_keywords_are_local_and_structured():
    messages = [
        {"role": "user", "content": "检查 EXP177 的 Jacobian 因果对照", "created_at": ""},
        {"role": "assistant", "content": "对照已经通过，结果支持状态追踪机制。", "created_at": ""},
    ]

    tldr = conversation_tldr("EXP177 Jacobian 检查", messages)
    summary = conversation_summary("EXP177 Jacobian 检查", messages)
    keywords = extract_keywords("EXP177 Jacobian 检查", tldr)

    assert tldr.startswith("- **判断**：结果支持状态追踪机制。")
    assert "- **依据**：对照已经通过。" in tldr
    assert "任务：" not in tldr
    assert summary["objective"].startswith("检查 EXP177")
    assert summary["result"] == tldr
    assert "…" not in summary["result"]
    assert summary["experiment_ids"] == ["EXP177"]
    assert "EXP177" in keywords
    assert any(keyword.lower() == "jacobian" for keyword in keywords)


def test_conversation_conclusion_is_summarized_at_clause_boundaries():
    messages = [
        {"role": "user", "content": "汇总 EXP183 的验证结果", "created_at": ""},
        {
            "role": "assistant",
            "content": (
                "核心结论：实验已经通过，结果支持 quotient flow 解释，"
                "关键对照的准确率达到 94%，但当前只验证了两个群，不能说明该机制对所有群都成立。"
            ),
            "created_at": "",
        },
    ]

    summary = conversation_summary("EXP183 结果汇总", messages)

    assert "- **判断**：结果支持 quotient flow 解释。" in summary["result"]
    assert "- **依据**：关键对照的准确率达到 94%。" in summary["result"]
    assert "- **边界**：不能说明该机制对所有群都成立。" in summary["result"]
    assert "…" not in summary["result"]
    assert not summary["result"].endswith("...")


def test_experiment_details_explain_unsettled_results(tmp_path: Path):
    workspace = tmp_path / "JSpace"
    prereg = workspace / "docs" / "exp13_preregistration.md"
    result = workspace / "results" / "exp13" / "metrics.json"
    prereg.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    prereg.write_text(
        "# Exp13 preregistration\n\n## Question\n\nDoes the control survive?",
        encoding="utf-8",
    )
    result.write_text("{}", encoding="utf-8")

    details = experiment_details(
        workspace,
        [("doc", prereg), ("result", result)],
        settlement=None,
        prereg=prereg,
        fallback="Exp13 summary",
    )

    result_section = next(
        section for section in details["sections"] if section["label"] == "结果与结论"
    )
    assert "已有 1 个结果文件" in result_section["body"]
    assert "尚未找到结算或结论文档" in result_section["body"]


def test_sync_conversations_experiments_and_paper_dedup(tmp_path: Path):
    workspace = tmp_path / "JSpace"
    user_home = tmp_path / "home"
    (workspace / "experiments").mkdir(parents=True)
    (workspace / "results" / "exp12_smoke").mkdir(parents=True)
    (workspace / "docs").mkdir(parents=True)
    (workspace / "experiments" / "exp12_demo.py").write_text("# demo", encoding="utf-8")
    (workspace / "results" / "exp12_smoke" / "metrics.json").write_text("{}", encoding="utf-8")
    (workspace / "docs" / "exp12_demo_settlement.md").write_text(
        "# Exp12 settlement — the intervention supports the mechanism\n\n"
        "## Verdict\n\nThe intervention supports the preregistered mechanism with a held-out control.\n\n"
        "## Results\n\nAccuracy improved from 0.50 to 0.81 on the frozen evaluation set.",
        encoding="utf-8",
    )
    (workspace / "docs" / "exp12_demo_preregistration.md").write_text(
        "# Exp12 preregistration — test the causal mechanism\n\n"
        "## Question\n\nDoes replacing the **candidate state** rescue the held-out failures?\n\n"
        "\\[\\Delta a = a_{patched} - a_{baseline}\\]\n\n"
        "## Method\n\nPatch the candidate state and compare it with an identity control.",
        encoding="utf-8",
    )
    pycache = workspace / "scripts" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "exp12_unhelpful.cpython-312.pyc").write_bytes(b"compiled")

    codex_path = user_home / ".codex" / "sessions" / "2026" / "08" / "rollout-test.jsonl"
    write_jsonl(codex_path, [
        {"timestamp": "2026-08-11T10:00:00+00:00", "type": "session_meta", "payload": {"id": "abc", "cwd": str(workspace)}},
        {"timestamp": "2026-08-11T10:01:00+00:00", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "检查 exp12 的因果对照"}]}},
        {"timestamp": "2026-08-11T10:02:00+00:00", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "对照通过，建议记录 holdout。"}]}},
    ])

    claude_path = user_home / ".claude" / "projects" / "jspace" / "claude.jsonl"
    write_jsonl(claude_path, [
        {"type": "user", "sessionId": "def", "cwd": str(workspace), "timestamp": "2026-08-11T11:00:00+00:00", "message": {"role": "user", "content": "复核实验结论"}},
        {"type": "assistant", "sessionId": "def", "cwd": str(workspace), "timestamp": "2026-08-11T11:01:00+00:00", "message": {"role": "assistant", "content": [{"type": "text", "text": "结论和证据一致。"}]}},
    ])

    index = ResearchIndex(workspace, state_dir=tmp_path / "state", user_home=user_home)
    try:
        index.conn.execute(
            """
            INSERT INTO experiments(
                key,title,status,status_label,source_path,updated_at,metadata_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                "EXP99",
                "Cached Experiment.Cpython 312",
                "draft",
                "草稿",
                "scripts\\__pycache__\\exp99_cached.cpython-312.pyc",
                "2026-08-12T00:00:00+00:00",
                "{}",
            ),
        )
        index.conn.commit()
        stats = index.sync_conversations()
        assert stats["updated"] == 2
        assert {item["provider"] for item in index.list_sessions()} == {"codex", "claude"}
        assert all(not item["tldr"].startswith("任务：") for item in index.list_sessions())
        assert all(item["summary"]["result"] for item in index.list_sessions())
        assert all(item["keywords"] for item in index.list_sessions())

        assert index.sync_experiments() == 1
        experiments = index.list_experiments()
        assert len(experiments) == 1
        experiment = experiments[0]
        assert experiment["key"] == "EXP12"
        assert experiment["status"] == "settled"
        assert experiment["result_count"] == 1
        assert "Cpython" not in experiment["title"]
        details = experiment["metadata"]["details"]
        assert details["overview"].startswith("Does replacing")
        assert "**candidate state**" in details["overview_markdown"]
        assert r"\[\Delta a = a_{patched} - a_{baseline}\]" in details[
            "overview_markdown"
        ]
        assert [section["label"] for section in details["sections"]] == [
            "研究问题",
            "实验方法",
            "结果与结论",
        ]
        assert details["sections"][2]["body"].startswith(
            "The intervention supports"
        )
        assert "**candidate state**" in details["sections"][0]["markdown"]
        assert any(group["label"] == "结果文件" for group in details["artifacts"])

        first = index.register_paper(title="A Study of J Space", doi="10.1000/XYZ", note="first")
        second = index.register_paper(title="A revised title", doi="https://doi.org/10.1000/xyz", note="updated")
        assert first["id"] == second["id"]
        assert len(index.list_papers()) == 1
        assert index.list_papers()[0]["note"] == "updated"
    finally:
        index.close()


def test_backfill_builds_historical_daily_tldr_and_keeps_legacy_experiment(tmp_path: Path):
    workspace = tmp_path / "JSpace"
    workspace.mkdir()
    index = ResearchIndex(workspace, state_dir=tmp_path / "state", user_home=tmp_path / "home")
    try:
        index.conn.execute(
            """
            INSERT INTO daily_digests(day,auto_body,stats_json,generated_at)
            VALUES(?,?,?,?)
            """,
            (
                "2026-08-10",
                "今天沉淀了 0 个 AI 对话、1 个实验变动。\n\n实验推进：\n• EXP42 · 有结果 · historical control",
                '{"sessions": 0, "experiments": 1, "papers": 0}',
                "2026-08-10T23:00:00+00:00",
            ),
        )
        index.conn.commit()

        result = index.backfill_summaries()
        digest = index.get_digest("2026-08-10")

        assert result["daily_tldrs_built"] >= 2
        assert "## 实验" in digest["auto_body"]
        assert "## 调研" in digest["auto_body"]
        assert "## 结果" in digest["auto_body"]
        assert "## 关键词" in digest["auto_body"]
        assert "EXP42" in digest["auto_body"]
        assert digest["summary_version"] == 9
    finally:
        index.close()


def test_daily_digest_explains_experiments_results_and_research_in_plain_language(tmp_path: Path):
    workspace = tmp_path / "JSpace"
    workspace.mkdir()
    index = ResearchIndex(workspace, state_dir=tmp_path / "state", user_home=tmp_path / "home")
    try:
        index.conn.execute(
            """
            INSERT INTO experiments(
                key,title,status,status_label,summary,updated_at,metadata_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                "EXP174",
                "结算：架构买速度不买结构——前沿之外零信息三架构成立，egj(17–100)=.5344",
                "settled",
                "已结论",
                "字面带超出冻结区间，但前沿之外恢复到随机水平。",
                "2026-08-24T18:00:00+00:00",
                json.dumps(
                    {
                        "details": {
                            "sections": [
                                {
                                    "label": "结果与结论",
                                    "body": "结果支持前沿推进解释，但 $F_e \\le 12$ 的边界被打穿。",
                                }
                            ]
                        }
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        sessions = [
            (
                "paper-read",
                "你是一次文献全文精读任务的执行代理。今天核对论文图表和版本差异。",
                {
                    "objective": "精读论文",
                    "approach": "比较 v1、v2 和 Figure 6。",
                    "result": "确认版本差异。",
                    "next_step": "继续核查。",
                },
            ),
            (
                "novelty-scan",
                "你是一次文献撞车扫描（novelty scan）的执行代理。",
                {
                    "objective": "检查研究想法是否被占用",
                    "approach": "检索相关论文。",
                    "result": "核心想法未被直接覆盖，但找到相近工作。",
                    "next_step": "补充引用。",
                },
            ),
        ]
        for session_id, title, summary in sessions:
            index.conn.execute(
                """
                INSERT INTO sessions(
                    id,provider,title,ended_at,source_path,source_mtime,preview,message_count,
                    note,indexed_at,tldr,summary_json,keywords_json,summary_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    "codex",
                    title,
                    "2026-08-24T20:00:00+00:00",
                    str(tmp_path / f"{session_id}.jsonl"),
                    1.0,
                    "",
                    2,
                    "",
                    "2026-08-24T20:00:00+00:00",
                    summary["result"],
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(
                        ["你是一次文献全文精读任务", "ToolSearch"]
                        if session_id == "paper-read"
                        else ["撞车扫描", "执行代理"],
                        ensure_ascii=False,
                    ),
                    7,
                ),
            )
        index.conn.commit()

        digest = index.build_digest("2026-08-24")

        assert digest["tldr"].startswith("今天的主线是")
        assert "不同架构中的信息前沿" in digest["tldr"]
        assert "- **实验**：推进 1 项实验" in digest["tldr"]
        assert "- **结果**：EXP174 只部分支持" in digest["tldr"]
        assert "- **调研**：" in digest["tldr"]
        assert "- **下一步**：" in digest["tldr"]
        assert "1 组论文精读" in digest["tldr"]
        assert "新颖性扫描" in digest["tldr"]
        assert "没有发现核心想法被直接覆盖" in digest["tldr"]
        assert "egj" not in digest["tldr"]
        assert "$" not in digest["tldr"]
        assert "执行代理" not in digest["tldr"]
        assert "论文精读" in digest["keywords"]
        assert "新颖性扫描" in digest["keywords"]
        assert "ToolSearch" not in digest["keywords"]
        assert "执行代理" not in digest["keywords"]
        assert digest["sections"]["experiments"][0]["result"].startswith("实验已经完成")
        assert digest["summary_version"] == 9
    finally:
        index.close()
