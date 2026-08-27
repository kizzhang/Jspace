"""Local-first index for the JSpace research workbench.

Only Python's standard library is used so the workbench can run inside the
existing research environment without adding packages to the main project.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


EXPERIMENT_RE = re.compile(r"(?i)(?:^|[_-])(exp\d+[a-z0-9]*)(?:[_-]|$)")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]{1,320})\]\((https?://[^)\s]+)\)", re.I)
WEB_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+", re.I)
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
CWD_BYTES_RE = re.compile(rb'"cwd"\s*:\s*"((?:\\.|[^"\\])*)"')
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
RESPONSE_ITEM_BYTES_RE = re.compile(rb'"type"\s*:\s*"response_item"')
MESSAGE_BYTES_RE = re.compile(rb'"type"\s*:\s*"message"')
USER_ROLE_BYTES_RE = re.compile(rb'"role"\s*:\s*"user"')
ASSISTANT_ROLE_BYTES_RE = re.compile(rb'"role"\s*:\s*"assistant"')
STRING_CONTENT_BYTES_RE = re.compile(rb'"content"\s*:\s*"')
TEXT_PART_BYTES_RE = re.compile(rb'"type"\s*:\s*"text"')
TITLE_EVENT_BYTES_RE = re.compile(rb'"type"\s*:\s*"(?:custom-title|ai-title)"')
SUMMARY_VERSION = 9
DIGEST_VERSION = 9
EXPERIMENT_ID_RE = re.compile(r"\bEXP\s*\d+[A-Z0-9]*\b", re.I)
ENGLISH_KEYWORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*\b")
CHINESE_TOPIC_TERMS = (
    "群 Transformer", "梯度相消", "梯度饥饿", "状态追踪", "因果干预", "因果解除",
    "注意力汇聚", "注意力沉降", "路径积分", "局部雅可比", "雅可比", "对称性",
    "置换不变性", "置换追踪", "绑定机制", "机制向量", "零样本", "少样本",
    "预注册", "消融实验", "因果对照", "表征探针", "机制解释", "外部基准",
    "数据生成", "训练动力学", "群论机制", "表示学习", "反事实干预",
)
ENGLISH_STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "assistant", "automation", "before",
    "being", "can", "codex", "code", "could", "daily", "does", "each", "from", "have",
    "into", "jspace", "memory", "more", "not", "only", "result", "script", "should",
    "that", "the", "their", "then", "this", "through", "tldr", "using", "was", "were",
    "what", "when", "where", "which", "with", "would", "your", "codex_home",
}
RESULT_CUES = (
    "结论", "结果", "发现", "表明", "支持", "不支持", "确认", "验证", "通过", "失败",
    "提升", "下降", "显著", "判定", "意味着", "说明", "证明", "达到", "收敛", "复现",
    "总判定", "总评", "总体", "核心结论", "结论先行", "一句话", "verdict", "result",
    "found", "finding", "support", "fail", "improve", "confirm",
)
EVIDENCE_CUES = (
    "证据", "数据", "指标", "对照", "实验", "测得", "观察", "曲线", "表格", "分析",
    "机制", "方法", "运行", "比较", "测试", "探针", "样本", "准确率", "损失", "消融",
    "evidence", "metric", "control", "benchmark", "probe", "accuracy", "loss", "ablation",
)
NEXT_CUES = (
    "下一步", "建议", "需要", "必须", "应当", "优先", "继续", "待补", "计划", "再做",
    "next", "should", "must", "recommend", "follow-up", "todo",
)
BOUNDARY_CUES = (
    "但", "不过", "然而", "边界", "限制", "局限", "尚未", "仍未", "未能", "不能说明",
    "不代表", "不等于", "仅能", "只说明", "只支持", "仍需", "待验证", "不承重", "反例",
    "ambiguous", "uncertain", "limitation", "however", "but ",
)
BOILERPLATE_CUES = (
    "我会先", "我先", "正在", "接下来我", "我将", "稍等", "开始检查", "脚本仍在运行",
    "现在执行", "我会把", "我来", "先读取", "先检查",
)
META_EVIDENCE_CUES = ("我的责任", "我第一次", "漏掉", "没把", "没有把", "抱歉", "我之前")
GENERIC_KEYWORDS = ("实验", "调研", "结果", "结论", "模型", "对话", "关键词", "日报", "测试", "评估")
SCHOLARLY_HOSTS = (
    "arxiv.org", "doi.org", "openreview.net", "aclanthology.org",
    "transformer-circuits.pub", "proceedings.mlr.press", "proceedings.iclr.cc",
    "proceedings.neurips.cc", "iclr.cc", "icml.cc", "neurips.cc",
    "ojs.aaai.org", "jmlr.org", "dl.acm.org", "ieeexplore.ieee.org",
    "openaccess.thecvf.com", "nature.com", "science.org", "link.springer.com",
    "biorxiv.org", "pubmed.ncbi.nlm.nih.gov",
)
GENERIC_PAPER_LABELS = {
    "论文", "论文正文", "原文", "来源", "链接", "全文", "正文", "paper", "pdf",
    "html", "here", "openreview", "arxiv", "arxiv v1", "arxiv v2", "arxiv v3",
}
LOCAL_PDF_CATALOG = {
    "liu_2023_transformers_learn_shortcuts_to_automata": {
        "title": "Transformers Learn Shortcuts to Automata",
        "authors": "Liu et al.", "year": 2023, "arxiv_id": "2210.10749",
    },
    "nanda_2023_progress_measures_grokking": {
        "title": "Progress Measures for Grokking via Mechanistic Interpretability",
        "authors": "Nanda et al.", "year": 2023, "arxiv_id": "2301.05217",
    },
    "chughtai_2023_group_operations": {
        "title": "A Toy Model of Universality: Reverse Engineering How Networks Learn Group Operations",
        "authors": "Chughtai, Chan & Nanda", "year": 2023, "arxiv_id": "2302.03025",
    },
    "stander_2024_group_multiplication_cosets": {
        "title": "Grokking Group Multiplication with Cosets",
        "authors": "Stander et al.", "year": 2024, "arxiv_id": "2312.06581",
    },
    "he_2026_spectral_group_composition": {
        "title": "Neural Networks Provably Learn Spectral Representations for Group Composition",
        "authors": "He et al.", "year": 2026, "arxiv_id": "2606.02993",
    },
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ts_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def clean_text(value: str | None, limit: int | None = None) -> str:
    text = SPACE_RE.sub(" ", (value or "").replace("\x00", " ")).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def transcript_text(value: str | None) -> str:
    """Remove transport/UI noise while preserving research content."""
    text = value or ""
    text = re.sub(
        r"(?mi)^\s*(?:Automation(?: ID| memory)?|Last run):.*$",
        " ",
        text,
    )
    text = re.sub(r"```.*?```", " （含代码、配置或结果表） ", text, flags=re.S)
    text = re.sub(r"<(?:recommended_plugins|environment_context)[^>]*>.*?</[^>]+>", " ", text, flags=re.S | re.I)
    text = re.sub(r"::[a-z-]+\{[^\n]*\}", " ", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"(?m)^\s*[#>*+-]+\s*", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def transcript_sentences(value: str | None, limit: int = 80) -> list[str]:
    text = transcript_text(value)
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+(?=[A-Z\u3400-\u9fff])|\n+", text)
    sentences: list[str] = []
    for part in parts:
        # Keep the complete source sentence here. Summaries are shortened later
        # at clause boundaries; truncating before extraction used to leave many
        # stored conclusions ending in a literal ellipsis.
        sentence = clean_text(part.replace("|", "；")).strip("； ")
        if re.fullmatch(r"[-:；\s]+", sentence):
            continue
        if sentence.count("；") >= 2 and all(term in sentence for term in ("实验", "结果", "状态")) and len(sentence) < 60:
            continue
        if len(sentence) < 6 or sentence in sentences:
            continue
        sentences.append(sentence)
        if len(sentences) >= limit:
            break
    return sentences


def plain_excerpt(value: str | None, limit: int = 180) -> str:
    sentences = transcript_sentences(value, 1)
    return clean_text(sentences[0] if sentences else "", limit)


def _join_chinese(values: list[str]) -> str:
    items = [value for value in values if value]
    if len(items) <= 1:
        return items[0] if items else ""
    return "、".join(items[:-1]) + "和" + items[-1]


def _plain_keyword(value: str) -> str:
    """Keep research concepts while dropping prompt and tool residue."""
    keyword = clean_text(value, 48)
    lowered = keyword.lower()
    if any(noise in lowered for noise in ("执行代理", "toolsearch", "websearch", "webfetch")):
        return ""
    if "文献全文精读" in keyword or "论文精读" in keyword:
        return "论文精读"
    if "撞车扫描" in keyword or "novelty scan" in lowered:
        return "新颖性扫描"
    if keyword.startswith(("你是一次", "请执行", "帮我")) or len(keyword) > 28:
        return ""
    return keyword


def _plain_experiment_topic(title: str, key: str = "") -> str:
    """Turn ledger-style experiment titles into short, readable topics."""
    text = transcript_text(title).replace("_", " ")
    text = EXPERIMENT_ID_RE.sub(" ", text)
    text = re.sub(
        r"(?i)^\s*(?:结算|预注册|复核|实验|结果|settlement|preregistration)\s*[：:—-]*\s*",
        "",
        text,
    )
    lowered = text.lower()
    if "跨群" in text and ("机制" in text or "扩展" in text):
        return "跨群机制扩展"
    if "local chain" in lowered:
        return "本地实验链路"
    if re.fullmatch(r"\s*gpu\d*\s*", lowered):
        return "GPU 运行链路"
    if "freeze manifest" in lowered or "冻结清单" in text:
        return "实验冻结配置"
    if "架构" in text and "前沿" in text:
        return "不同架构中的信息前沿"
    if "s5" in lowered and ("锚点" in text or "不变量" in text):
        return "S5 锚点与零信息不变量"
    if "输入幅度" in text and ("前沿" in text or "特征标" in text):
        return "输入幅度对特征学习和信息前沿的影响"
    if ("训长" in text or "训练长度" in text) and "前沿" in text:
        return "训练长度对信息前沿的影响"
    if "seed" in lowered and ("定格" in text or "稳定" in text):
        return "多随机种子稳定性复核"
    if "雅可比" in text or "jacobian" in lowered:
        return "雅可比机制"
    if "梯度" in text and ("相消" in text or "饥饿" in text):
        return "梯度相消与梯度饥饿"
    if "绑定" in text or "binding" in lowered:
        return "绑定机制"
    if "attention" in lowered or "注意力" in text:
        return "注意力机制"

    text = re.split(r"[—|]", text, maxsplit=1)[0]
    text = re.sub(
        r"(?i)(?:全中|落地|命中|成立|通过|supported|settled|closure|gpu\d*|local chain)",
        "",
        text,
    )
    text = re.sub(r"\s*\([^)]{12,}\)\s*", " ", text)
    text = clean_text(text.strip(" ：:—-·,，。"), 52)
    return text or key or "实验进展"


def _plain_experiment_result(item: dict[str, Any], raw_result: str) -> str:
    """Describe an experiment outcome without replaying formulas or ledger jargon."""
    status = clean_text(item.get("status_label") or item.get("status") or "")
    combined = f"{item.get('title', '')} {raw_result}".lower()
    waiting = any(cue in combined for cue in ("尚未发现", "尚未找到", "暂无", "待运行", "待整理"))
    configured = any(cue in status for cue in ("计划", "配置", "草稿", "预注册"))
    negative = any(cue in combined for cue in ("失败", "不支持", "未通过", "不成立", "否定", "failed", "unsupported"))
    positive = any(
        cue in combined
        for cue in ("全中", "成立", "通过", "支持", "命中", "收敛", "supported", "confirmed", "passed")
    )
    mixed = positive and any(cue in combined for cue in ("但", "不过", "部分", "边界", "例外", "打穿", "mixed"))

    if configured and waiting:
        return "实验已经配置好，尚未形成结果。"
    if waiting:
        return "实验已有记录更新，但还没有可确认的结果。"
    if negative and positive:
        return "实验已经完成，结果有支持也有反例，需要继续检查边界条件。"
    if negative:
        return "实验已经完成，但结果没有支持原来的判断。"
    if mixed:
        return "实验已经完成，结果部分支持预期，同时发现了需要继续解释的边界情况。"
    if positive:
        return "实验已经完成，结果支持原来的判断。"
    if any(cue in status for cue in ("结论", "结算", "完成")):
        return "实验已经完成并形成结论。"
    if any(cue in status for cue in ("结果", "运行")):
        return "实验已经产生结果，结论仍在整理。"
    return "实验有新的进展，结果仍在整理。"


def _research_kind(title: str) -> str:
    lowered = title.lower()
    if any(cue in lowered for cue in ("jspace 每日科研整理", "research_workbench", "daily_sync", "启动工作台")):
        return "maintenance"
    if "文献全文精读" in title or "论文精读" in title or "full paper" in lowered:
        return "paper_read"
    if any(cue in lowered for cue in ("撞车扫描", "novelty scan", "artifact 占用", "占用分析")):
        return "novelty"
    if any(cue in title for cue in ("文献", "论文", "相关工作")):
        return "literature"
    return "other"


def _daily_research_items(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate prompt-like research chats into a small number of readable activities."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sessions:
        kind = _research_kind(item.get("title", ""))
        if kind != "maintenance":
            grouped[kind].append(item)

    output: list[dict[str, Any]] = []
    for kind in ("paper_read", "novelty", "literature", "other"):
        items = grouped.get(kind, [])
        if not items:
            continue
        combined = " ".join(
            " ".join(
                str((item.get("summary") or {}).get(field, ""))
                for field in ("objective", "approach", "result", "next_step")
            )
            for item in items
        )
        keyword_values: list[str] = []
        for item in items:
            for keyword in item.get("keywords", []):
                if keyword not in keyword_values and not any(
                    noise in keyword.lower()
                    for noise in ("执行代理", "toolsearch", "websearch", "webfetch", "jspace")
                ):
                    keyword_values.append(keyword)

        if kind == "paper_read":
            title = f"论文精读（{len(items)} 次）"
            objective = "精读相关论文，核对方法、关键图表和版本差异。"
            approach = (
                "重点比较了论文版本、实验设置和作者给出的证据。"
                if any(cue in combined.lower() for cue in ("版本", "v1", "v2", "figure", "table"))
                else "重点核对了论文的方法、实验设置和作者给出的证据。"
            )
        elif kind == "novelty":
            title = f"相关工作与新颖性扫描（{len(items)} 次）"
            objective = "检索相近论文，判断核心想法是否已经被已有工作覆盖。"
            unoccupied = any(
                cue in combined.lower()
                for cue in ("未被占", "没有发现核心", "未被直接", "未被覆盖", "not occupied")
            )
            approach = (
                "目前没有发现核心想法被直接覆盖，但找到了若干相近工作，需要补充引用和对照。"
                if unoccupied
                else "筛出了若干相近工作，并记录了需要继续核查的论文和对照方向。"
            )
        elif kind == "literature":
            title = f"文献调研（{len(items)} 次）"
            objective = "查找与当前课题相关的论文和已有结论。"
            approach = "整理了相近方法、关键证据和需要继续核查的文献。"
        else:
            first = items[0]
            topic = _plain_experiment_topic(first.get("title", ""))
            title = topic if len(items) == 1 else f"{topic}等 {len(items)} 项调研"
            objective = f"围绕“{topic}”整理问题和现有证据。"
            approach = "梳理了已有结果、可能的解释和下一步需要验证的问题。"

        output.append(
            {
                "session_id": items[0]["id"],
                "title": title,
                "provider": items[0]["provider"],
                "objective": objective,
                "approach": approach,
                "keywords": keyword_values[:5],
                "count": len(items),
                "kind": kind,
            }
        )
    return output


def _sentence_score(sentence: str, cues: tuple[str, ...], position: int, total: int) -> int:
    lowered = sentence.lower()
    score = sum(16 for cue in cues if cue.lower() in lowered)
    score += min(len(sentence), 180) // 24
    score += int(6 * position / max(total - 1, 1))
    if EXPERIMENT_ID_RE.search(sentence):
        score += 7
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|倍|个|项|层|step|epoch|k\b)", sentence, re.I):
        score += 7
    if any(cue in sentence for cue in BOILERPLATE_CUES):
        score -= 28
    if any(cue in sentence for cue in META_EVIDENCE_CUES):
        score -= 22
    if cues == RESULT_CUES and any(cue in sentence for cue in ("总判定", "总评", "核心结论", "结论先行", "一句话总览")):
        score += 28
    if cues == NEXT_CUES and "下一步" in sentence:
        score += 30
    if cues == NEXT_CUES and any(cue in sentence for cue in ("正确优先级", "优先级应", "应改成")):
        score += 24
    if sentence.startswith(("好的", "可以", "是的", "没问题")) and len(sentence) < 45:
        score -= 8
    return score


def _best_sentence(sentences: list[str], cues: tuple[str, ...], fallback_last: bool = True) -> str:
    if not sentences:
        return ""
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (_sentence_score(item[1], cues, item[0], len(sentences)), item[0]),
        reverse=True,
    )
    best = ranked[0][1]
    best_index = ranked[0][0]
    if best.rstrip().endswith(("：", ":")) and best_index + 1 < len(sentences):
        best = clean_text(f"{best}{sentences[best_index + 1]}")
    if _sentence_score(best, cues, ranked[0][0], len(sentences)) <= 2 and fallback_last:
        useful = [sentence for sentence in sentences if not any(cue in sentence for cue in BOILERPLATE_CUES)]
        return useful[-1] if useful else sentences[-1]
    return best


def _summary_clauses(value: str) -> list[str]:
    """Split prose at top-level punctuation without breaking quotes or formulas."""
    parts: list[str] = []
    buffer: list[str] = []
    depths = {"(": 0, "[": 0, "{": 0}
    closers = {")": "(", "]": "[", "}": "{"}
    ascii_quote = False
    curly_quote = False
    for index, character in enumerate(value):
        if character == '"':
            ascii_quote = not ascii_quote
        elif character == "“":
            curly_quote = True
        elif character == "”":
            curly_quote = False
        elif not ascii_quote and not curly_quote:
            if character in depths:
                depths[character] += 1
            elif character in closers and depths[closers[character]]:
                depths[closers[character]] -= 1
        buffer.append(character)
        top_level = not ascii_quote and not curly_quote and not any(depths.values())
        period_boundary = False
        if top_level and character == ".":
            tail = value[index + 1:]
            next_character = tail.lstrip()[:1]
            period_boundary = not next_character or (
                bool(tail) and tail[:1].isspace()
                and bool(re.match(r"[A-Z\u3400-\u9fff\"“*\[]", next_character))
            )
        quote_boundary = False
        if top_level and character in "\"”’" and index and value[index - 1] in ".!?。！？":
            tail = value[index + 1:]
            quote_boundary = bool(tail) and tail[:1].isspace() and bool(
                re.match(r"[A-Z\u3400-\u9fff\"“*\[]", tail.lstrip()[:1])
            )
        if top_level and (character in "。！？!?；;，,：:—–" or period_boundary or quote_boundary):
            part = "".join(buffer).strip()
            if part:
                parts.append(part)
            buffer = []
    tail = "".join(buffer).strip()
    if tail:
        parts.append(tail)
    return parts


def _summary_fragment(
    value: str,
    cues: tuple[str, ...],
    *,
    max_chars: int = 220,
    max_parts: int = 1,
) -> str:
    """Condense a source sentence into complete, information-bearing clauses."""
    text = clean_text(value).strip(" -*#\t")
    text = re.sub(
        r"(?i)^(?:总体|核心)?(?:结论|判断|结果|总评|总判定|一句话总览|verdict|result)\s*[：:\-—]*\s*",
        "",
        text,
    )
    text = re.sub(r"(?:\.{3,}|…)+$", "", text).strip()
    if not text:
        return ""

    # Commas often separate the claim from its evidence or qualification. Keeping
    # them as separate candidates produces an actual summary instead of a clipped
    # copy of the source paragraph.
    raw_parts = _summary_clauses(text)
    parts: list[str] = []
    for raw in raw_parts:
        part = clean_text(raw).strip(" -*#；;，,：:—–")
        part = re.sub(r"(?:\.{3,}|…)+$", "", part).strip()
        if len(part) >= 6 and part not in parts:
            parts.append(part)
    if not parts:
        parts = [text]

    def score(item: tuple[int, str]) -> tuple[int, int, int]:
        position, part = item
        lowered = part.lower()
        cue_score = sum(18 for cue in cues if cue.lower() in lowered)
        numeric_score = 7 if re.search(r"\d", part) or EXPERIMENT_ID_RE.search(part) else 0
        readable_length = 7 if 12 <= len(part) <= 180 else 2
        return cue_score + numeric_score + readable_length, -position, -len(part)

    ranked = sorted(enumerate(parts), key=score, reverse=True)
    chosen: list[tuple[int, str]] = []
    for position, part in ranked:
        projected = sum(len(selected) for _, selected in chosen) + len(part) + 1
        if chosen and projected > max_chars:
            continue
        chosen.append((position, part))
        if len(chosen) >= max_parts:
            break
    if not chosen:
        chosen = [(0, parts[0])]
    chosen.sort(key=lambda item: item[0])
    chinese = bool(re.search(r"[\u3400-\u9fff]", "".join(part for _, part in chosen)))
    separator = "；" if chinese else "; "
    summary = separator.join(part.rstrip("。！？!?；;，, ") for _, part in chosen).strip()
    summary = re.sub(r"(?i)^(?:and|but|however|while)\s+", "", summary).strip()
    if summary and not re.search(r"[。！？.!?](?:[\"'”’\]\)*]+)?$", summary):
        summary += "。" if chinese else "."
    return summary


def _boundary_sentence(sentences: list[str], excluded: set[str]) -> str:
    candidates: list[tuple[int, int, str]] = []
    for position, sentence in enumerate(sentences):
        if sentence in excluded:
            continue
        lowered = sentence.lower()
        hits = sum(1 for cue in BOUNDARY_CUES if cue.lower() in lowered)
        if not hits:
            continue
        score = hits * 24 + min(len(sentence), 180) // 30 + position
        candidates.append((score, position, sentence))
    return max(candidates, default=(0, 0, ""))[2]


def _conclusion_summary(judgment: str, evidence: str = "", boundary: str = "") -> str:
    lines = [f"- **判断**：{judgment}"]
    if evidence and evidence not in judgment and judgment not in evidence:
        lines.append(f"- **依据**：{evidence}")
    if boundary and boundary not in judgment and judgment not in boundary and boundary not in evidence:
        lines.append(f"- **边界**：{boundary}")
    return "\n".join(lines)


def conversation_summary(title: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """Extract a result-first research brief from the full local transcript."""
    user_sentences: list[str] = []
    assistant_sentences: list[str] = []
    for message in messages:
        target = user_sentences if message.get("role") == "user" else assistant_sentences
        target.extend(transcript_sentences(message.get("content")))

    objective = user_sentences[0] if user_sentences else plain_excerpt(title, 220)
    result_source = _best_sentence(assistant_sentences, RESULT_CUES)
    if not result_source:
        result_source = "尚未形成可确认的研究结论。"
    if re.search(r"汇总|总览|总结|进度", title):
        ranked_results = sorted(
            enumerate(assistant_sentences),
            key=lambda item: (_sentence_score(item[1], RESULT_CUES, item[0], len(assistant_sentences)), item[0]),
            reverse=True,
        )
        highlights: list[str] = []
        for index, candidate in ranked_results:
            if _sentence_score(candidate, RESULT_CUES, index, len(assistant_sentences)) < 12:
                continue
            if candidate.rstrip().endswith(("：", ":")) and index + 1 < len(assistant_sentences):
                candidate = clean_text(candidate + assistant_sentences[index + 1])
            if candidate not in highlights:
                highlights.append(candidate)
            if len(highlights) >= 3:
                break
        if len(highlights) >= 2:
            result_source = "；".join(value.rstrip("。；; ") for value in highlights) + "。"
    evidence_candidates = [sentence for sentence in assistant_sentences if sentence != result_source]
    evidence_source = _best_sentence(evidence_candidates, EVIDENCE_CUES, fallback_last=False)
    if not evidence_source or _sentence_score(evidence_source, EVIDENCE_CUES, 0, 1) < 10:
        # A concise answer often states the test and the verdict in one sentence.
        # Reuse that sentence only when it contains a real evidence cue; clause
        # selection below keeps the evidence from duplicating the judgment.
        evidence_source = (
            result_source
            if _sentence_score(result_source, EVIDENCE_CUES, 0, 1) >= 10
            else ""
        )
    boundary_source = _boundary_sentence(
        assistant_sentences,
        {value for value in (result_source, evidence_source) if value},
    )
    if not boundary_source and any(cue.lower() in result_source.lower() for cue in BOUNDARY_CUES):
        boundary_source = result_source
    judgment = _summary_fragment(result_source, RESULT_CUES, max_chars=220)
    evidence = _summary_fragment(evidence_source, EVIDENCE_CUES, max_chars=180) if evidence_source else ""
    boundary = _summary_fragment(boundary_source, BOUNDARY_CUES, max_chars=180) if boundary_source else ""
    if not judgment:
        judgment = "尚未形成可确认的研究结论。"
    result = _conclusion_summary(judgment, evidence, boundary)
    approach = evidence or "对话中未单独沉淀证据摘要。"
    next_step = _best_sentence(assistant_sentences, NEXT_CUES, fallback_last=False)
    if not next_step or _sentence_score(next_step, NEXT_CUES, 0, 1) < 10:
        next_step = "未明确记录下一步。"
    experiment_ids = sorted(
        {re.sub(r"\s+", "", match.group(0)).upper() for match in EXPERIMENT_ID_RE.finditer(" ".join(user_sentences + assistant_sentences))}
    )
    tldr = result
    return {
        "objective": clean_text(objective, 260),
        "approach": approach,
        "result": result,
        "next_step": clean_text(next_step, 260),
        "experiment_ids": experiment_ids,
        "tldr": tldr,
    }


def conversation_tldr(title: str, messages: list[dict[str, str]]) -> str:
    return str(conversation_summary(title, messages)["tldr"])


def extract_keywords(*values: str, limit: int = 8) -> list[str]:
    """Extract stable research-oriented keywords from titles and summaries."""
    text = "\n".join(value for value in values if value)
    scored: dict[str, tuple[int, int, str]] = {}

    def add(value: str, score: int) -> None:
        keyword = clean_text(value, 32).strip(".,:;，。；：!?！？()[]{}")
        if len(keyword) < 2:
            return
        generic_hits = sum(term.lower() in keyword.lower() for term in GENERIC_KEYWORDS)
        if generic_hits >= 3 or normalize_title(keyword) in {normalize_title(term) for term in GENERIC_KEYWORDS}:
            return
        key = keyword.lower()
        previous = scored.get(key)
        candidate = (score, -len(keyword), keyword)
        if previous is None or candidate > previous:
            scored[key] = candidate

    for match in EXPERIMENT_ID_RE.finditer(text):
        add(re.sub(r"\s+", "", match.group(0)).upper(), 100)
    for term in CHINESE_TOPIC_TERMS:
        count = text.count(term)
        if count:
            add(term, 58 + min(count, 5))
    for match in re.finditer(r"[`“\"]([^`”\"]{3,28})[`”\"]", text):
        add(match.group(1), 48)
    for match in ENGLISH_KEYWORD_RE.finditer(text):
        token = match.group(0)
        key = token.lower()
        if key in ENGLISH_STOPWORDS or len(token) < 4 or token.isdigit():
            continue
        count = len(re.findall(rf"(?i)\b{re.escape(token)}\b", text))
        technical = token[0].isupper() or any(char.isupper() or char.isdigit() for char in token[1:]) or "-" in token or "_" in token
        if technical or count >= 2:
            add(token, 30 + min(count, 8) + (10 if technical else 0))

    title = plain_excerpt(values[0] if values else "", 40)
    title = re.sub(r"^(?:请|帮我|麻烦|做一个|看一下|看看|检查|分析|评估|调研|启动一下)\s*", "", title)
    title = re.sub(r"(?:实验)?(?:进度)?(?:汇总|总结|报告|分析|评估)$", "", title).strip()
    for phrase in re.split(r"\s*(?:的|以及|和|与|、|：|:|/|\|)\s*", title):
        phrase = clean_text(phrase, 28)
        if 3 <= len(phrase) <= 24 and normalize_title(phrase) not in {"未命名对话", "newchat"}:
            add(phrase, 54)

    ordered = sorted(scored.items(), key=lambda item: (-item[1][0], item[1][1], item[0]))
    result: list[str] = []
    for key, (_, _, display) in ordered:
        # Preserve canonical experiment casing; other English terms remain readable.
        result.append(key.upper() if EXPERIMENT_ID_RE.fullmatch(key) else display)
        if len(result) >= limit:
            break
    return result or ["未分类"]


def parse_keywords(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def normalize_title(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", (value or "").lower())


def normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    value = urllib.parse.unquote(value).strip()
    value = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", value, flags=re.I)
    match = DOI_RE.search(value)
    return match.group(0).rstrip(".,;)").lower() if match else ""


def normalize_arxiv(value: str | None) -> str:
    if not value:
        return ""
    match = ARXIV_RE.search(value)
    return re.sub(r"v\d+$", "", match.group(1), flags=re.I) if match else ""


def normalize_paper_url(value: str | None) -> str:
    """Canonicalize a scholarly link so repeated mentions collapse to one paper."""
    raw = html.unescape(value or "").strip().rstrip(".,;:，。；：")
    if not raw:
        return ""
    doi = normalize_doi(raw)
    if doi:
        return f"https://doi.org/{doi}"
    arxiv_id = normalize_arxiv(raw)
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return raw
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/")
    query = urllib.parse.parse_qs(parsed.query)
    if host == "openreview.net" and query.get("id"):
        return f"https://openreview.net/forum?id={query['id'][0]}"
    if host == "proceedings.mlr.press":
        match = re.match(r"(/v\d+/[^/]+)(?:/[^/]+\.pdf|\.html)$", path, re.I)
        if match:
            path = match.group(1) + ".html"
    if host == "aclanthology.org" and path.lower().endswith(".pdf"):
        path = path[:-4] + "/"
    return urllib.parse.urlunparse(("https", host, path, "", parsed.query, ""))


def is_scholarly_url(value: str) -> bool:
    canonical = normalize_paper_url(value)
    if not canonical:
        return False
    if normalize_doi(canonical) or normalize_arxiv(canonical):
        return True
    try:
        host = (urllib.parse.urlparse(canonical).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in SCHOLARLY_HOSTS)


def _plain_link_label(value: str) -> str:
    value = re.sub(r"[*_`~]", "", html.unescape(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" |—–-:：;,，。()（）[]")
    return clean_text(value, 300)


def _useful_paper_title(value: str) -> bool:
    title = _plain_link_label(value)
    lowered = title.lower()
    if not title or lowered in GENERIC_PAPER_LABELS:
        return False
    if re.fullmatch(r"(?:arxiv\s*[:v]?\s*)?\d{4}\.\d{4,5}(?:v\d+)?", lowered):
        return False
    if re.fullmatch(r"(?:openreview|pmlr|acl anthology)\s+[a-z0-9._/-]+", lowered):
        return False
    return len(title) >= 4 and bool(re.search(r"[A-Za-z\u3400-\u9fff]", title))


def _citation_hint(value: str) -> tuple[str, int | None, str]:
    text = _plain_link_label(re.sub(r"^\s*(?:\d+[.)]|[-+•])\s*", "", value or ""))
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None
    authors = ""
    title = ""
    if year_match:
        authors = text[: year_match.start()].strip(" ,，()（）")
        title = text[year_match.end():].strip(" ,，()（）:：—–-")
    else:
        author_match = re.match(r"(.{2,100}?(?:et al\.|\s&\s[^,，]+))[,，]\s*(.+)$", text, re.I)
        if author_match:
            authors, title = author_match.group(1), author_match.group(2)
    return clean_text(authors, 300), year, clean_text(title, 300)


def _citation_key(authors: str, year: int | None) -> str:
    surname = re.search(r"[A-Za-z][A-Za-z'’.-]+", authors or "")
    return f"{surname.group(0).lower()}:{year}" if surname and year else ""


def _fallback_paper_title(url: str) -> str:
    arxiv_id = normalize_arxiv(url)
    if arxiv_id:
        return f"arXiv {arxiv_id}"
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "文献").removeprefix("www.")
    query = urllib.parse.parse_qs(parsed.query)
    if host == "openreview.net" and query.get("id"):
        return f"OpenReview {query['id'][0]}"
    slug = Path(parsed.path.rstrip("/")).stem.replace("_", " ").replace("-", " ")
    return clean_text(f"{host} · {slug or '论文'}", 180)


def paper_candidates_from_text(value: str) -> list[dict[str, Any]]:
    """Extract cited papers from research prose without changing the source text."""
    text = value or ""
    heading_map: dict[str, tuple[str, int, str]] = {}
    for heading in re.findall(r"(?m)^#{2,6}\s+(.+?)\s*$", text):
        authors, year, title = _citation_hint(heading)
        key = _citation_key(authors, year)
        if key and _useful_paper_title(title):
            heading_map[key] = (authors, int(year), _plain_link_label(title))

    selected: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        markdown_spans: list[tuple[int, int]] = []
        raw_candidates: list[tuple[str, str, str, int]] = []
        for match in MARKDOWN_LINK_RE.finditer(line):
            markdown_spans.append((match.start(2), match.end(2)))
            raw_candidates.append((match.group(2), match.group(1), line[: match.start()], 50))
        for match in WEB_URL_RE.finditer(line):
            if any(start <= match.start() < end for start, end in markdown_spans):
                continue
            context = line[: match.start()]
            after = line[match.end():]
            after = re.split(r"[：|]", after, maxsplit=1)[0].strip(" —–-:：;,，。()（）")
            raw_candidates.append((match.group(0), after, context, 24))

        for raw_url, label, prefix, base_score in raw_candidates:
            if not is_scholarly_url(raw_url):
                continue
            url = normalize_paper_url(raw_url)
            authors, year, hinted_title = _citation_hint(prefix)
            key = _citation_key(authors, year)
            heading = heading_map.get(key)
            if heading:
                authors, year, heading_title = heading
            else:
                heading_title = ""
            if _useful_paper_title(label):
                title = _plain_link_label(label)
                score = base_score + min(len(title), 80)
            elif _useful_paper_title(heading_title):
                title = heading_title
                score = base_score + 65
            elif _useful_paper_title(hinted_title):
                title = _plain_link_label(hinted_title)
                score = base_score + min(len(title), 60)
            else:
                title = _fallback_paper_title(url)
                score = 10
            doi = normalize_doi(url)
            arxiv_id = normalize_arxiv(url)
            identity = f"doi:{doi}" if doi else f"arxiv:{arxiv_id}" if arxiv_id else f"url:{url}"
            candidate = {
                "title": title,
                "authors": authors,
                "year": year,
                "doi": doi,
                "arxiv_id": arxiv_id,
                "source_url": url,
                "score": score,
            }
            previous = selected.get(identity)
            if previous is None or candidate["score"] > previous["score"]:
                selected[identity] = candidate
    return list(selected.values())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def first_paragraph(path: Path, limit: int = 360) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = clean_text(re.sub(r"^[#>*`\-\s]+", "", block))
        if len(block) >= 40 and not block.lower().startswith(("import ", "from ")):
            paragraphs.append(block)
            break
    return clean_text(paragraphs[0] if paragraphs else "", limit)


def markdown_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return clean_text(match.group(1), 160) if match else ""


def markdown_sections(path: Path, limit: int = 2400) -> list[dict[str, str]]:
    """Return both renderable Markdown and a plain-text search excerpt."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    headings = list(re.finditer(r"(?m)^#{2,4}\s+(.+?)\s*$", text))
    sections: list[dict[str, str]] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        markdown = text[heading.end():end].strip()
        if len(markdown) > limit:
            cut = markdown.rfind("\n\n", 0, limit)
            markdown = markdown[: cut if cut >= limit // 2 else limit].rstrip() + "\n\n…"
        plain = re.sub(r"```.*?```", " （含代码示例） ", markdown, flags=re.S)
        plain = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"(?m)^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$", "", plain)
        plain = plain.replace("**", "").replace("__", "")
        plain = re.sub(r"[`>#|]", " ", plain)
        plain = re.sub(r"(?m)^\s*[-+]\s+", "", plain)
        plain = clean_text(plain, limit)
        if plain:
            sections.append(
                {
                    "heading": clean_text(heading.group(1), 100),
                    "body": plain,
                    "markdown": markdown,
                }
            )
    return sections


def experiment_details(
    workspace: Path,
    files: list[tuple[str, Path]],
    settlement: Path | None,
    prereg: Path | None,
    fallback: str,
) -> dict[str, Any]:
    docs = [path for kind, path in files if kind == "doc"]
    preferred_docs = [path for path in (prereg, settlement) if path]
    preferred_docs.extend(path for path in docs if path not in preferred_docs)
    section_cache = {path: markdown_sections(path) for path in preferred_docs}
    rules = (
        ("研究问题", re.compile(r"\b(question|objective|goal|hypothesis|purpose)\b|问题|目标|假设", re.I),
         [path for path in (prereg, settlement) if path] + docs),
        ("实验方法", re.compile(r"\b(method|design|protocol|setup|construction|contract|conditions?|battery|models?)\b|方法|设计|设置|流程|模型", re.I),
         [path for path in (prereg, settlement) if path] + docs),
        ("结果与结论", re.compile(r"\b(verdict|results?|conclusion|findings?|settlement)\b|结论|结果|判定", re.I),
         [path for path in (settlement, prereg) if path] + docs),
    )
    selected: list[dict[str, str]] = []
    for label, pattern, paths in rules:
        match = next(
            (
                (path, section)
                for path in paths
                for section in section_cache.get(path, [])
                if pattern.search(section["heading"])
            ),
            None,
        )
        if match:
            path, section = match
            selected.append(
                {
                    "label": label,
                    "heading": section["heading"],
                    "body": section["body"],
                    "markdown": section["markdown"],
                    "source": str(path.relative_to(workspace)),
                }
            )

    selected_by_label = {section["label"]: section for section in selected}
    result_count = sum(1 for kind, _ in files if kind == "result")
    fallbacks = {
        "研究问题": f"研究记录尚未单独标注研究问题。现有摘要：{fallback}",
        "实验方法": "研究记录尚未单独整理实验方法；可在下方相关材料中查看预注册文档和实验脚本。",
        "结果与结论": (
            f"已有 {result_count} 个结果文件，但尚未找到结算或结论文档。"
            if result_count
            else "尚未发现结果文件或结论文档。"
        ),
    }
    selected = [
        selected_by_label.get(
            label,
            {
                "label": label,
                "heading": label,
                "body": body,
                "markdown": body,
                "source": "",
            },
        )
        for label, body in fallbacks.items()
    ]

    overview = next(
        (section["body"] for section in selected if section["label"] == "研究问题"),
        next((section["body"] for section in selected), fallback),
    )
    overview_markdown = next(
        (section["markdown"] for section in selected if section["label"] == "研究问题"),
        overview,
    )
    kind_labels = {
        "source": "实验脚本",
        "script": "分析脚本",
        "launcher": "运行配置",
        "result": "结果文件",
        "doc": "研究记录",
        "manifest": "清单文件",
    }
    artifacts: list[dict[str, Any]] = []
    for kind, label in kind_labels.items():
        paths = [str(path.relative_to(workspace)) for file_kind, path in files if file_kind == kind]
        if paths:
            artifacts.append({"label": label, "count": len(paths), "paths": paths[:5]})
    return {
        "overview": clean_text(overview, 360),
        "overview_markdown": overview_markdown,
        "sections": selected,
        "artifacts": artifacts,
        "document": str((settlement or prereg).relative_to(workspace)) if (settlement or prereg) else "",
    }


@dataclass
class SyncStats:
    codex_sessions: int = 0
    claude_sessions: int = 0
    conversations_updated: int = 0
    experiments: int = 0
    papers: int = 0
    papers_refreshed: int = 0

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


class ResearchIndex:
    def __init__(
        self,
        workspace: Path,
        state_dir: Path | None = None,
        user_home: Path | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.user_home = (user_home or Path.home()).resolve()
        self.state_dir = (
            state_dir or self.workspace / "tools" / "research_workbench" / ".data"
        ).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "workbench.sqlite"
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                title TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                cwd TEXT,
                source_path TEXT UNIQUE NOT NULL,
                source_mtime REAL NOT NULL,
                preview TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                indexed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT,
                UNIQUE(session_id, ordinal)
            );

            CREATE TABLE IF NOT EXISTS experiments (
                key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                status_label TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                source_path TEXT,
                updated_at TEXT,
                source_count INTEGER NOT NULL DEFAULT 0,
                result_count INTEGER NOT NULL DEFAULT 0,
                doc_count INTEGER NOT NULL DEFAULT 0,
                launcher_count INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_key TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                authors TEXT NOT NULL DEFAULT '',
                year INTEGER,
                doi TEXT NOT NULL DEFAULT '',
                arxiv_id TEXT NOT NULL DEFAULT '',
                pdf_path TEXT NOT NULL DEFAULT '',
                pdf_hash TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                abstract TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'inbox',
                note TEXT NOT NULL DEFAULT '',
                metadata_updated_at TEXT,
                file_updated_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
            CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id);
            CREATE INDEX IF NOT EXISTS idx_papers_hash ON papers(pdf_hash);

            CREATE TABLE IF NOT EXISTS daily_digests (
                day TEXT PRIMARY KEY,
                tldr TEXT NOT NULL DEFAULT '',
                auto_body TEXT NOT NULL DEFAULT '',
                manual_note TEXT NOT NULL DEFAULT '',
                keywords_json TEXT NOT NULL DEFAULT '[]',
                stats_json TEXT NOT NULL DEFAULT '{}',
                summary_version INTEGER NOT NULL DEFAULT 0,
                generated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._ensure_column("sessions", "tldr", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "summary_json", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("sessions", "keywords_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("sessions", "summary_version", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("daily_digests", "tldr", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("daily_digests", "sections_json", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("daily_digests", "keywords_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("daily_digests", "summary_version", "INTEGER NOT NULL DEFAULT 0")
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS message_search "
                "USING fts5(session_id UNINDEXED, content, tokenize='unicode61')"
            )
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def sync_all(self, refresh_papers: bool = True) -> dict[str, Any]:
        stats = SyncStats()
        conversation = self.sync_conversations()
        stats.codex_sessions = conversation["codex_sessions"]
        stats.claude_sessions = conversation["claude_sessions"]
        stats.conversations_updated = conversation["updated"]
        stats.experiments = self.sync_experiments()
        self.sync_researched_papers()
        stats.papers = self.sync_pdf_inbox()
        if refresh_papers:
            stats.papers_refreshed = self.refresh_arxiv_papers() + self.refresh_due_papers()
        self.dedupe_papers()
        stats.papers = int(self.conn.execute("SELECT count(*) FROM papers").fetchone()[0])
        summaries = self.backfill_summaries()
        finished = now_iso()
        self.conn.execute(
            "INSERT INTO app_meta(key, value) VALUES('last_sync', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (finished,),
        )
        self.conn.commit()
        return {"ok": True, "last_sync": finished, **stats.as_dict(), **summaries}

    def _is_workspace(self, cwd: str | None) -> bool:
        if not cwd:
            return False
        try:
            candidate = Path(cwd).resolve()
            return candidate == self.workspace or self.workspace in candidate.parents
        except (OSError, ValueError):
            return os.path.normcase(cwd) == os.path.normcase(str(self.workspace))

    def _unchanged(self, source_path: Path) -> bool:
        row = self.conn.execute(
            "SELECT source_mtime FROM sessions WHERE source_path=?",
            (str(source_path),),
        ).fetchone()
        return bool(row and abs(float(row[0]) - source_path.stat().st_mtime) < 0.001)

    def _codex_title_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        index_path = self.user_home / ".codex" / "session_index.jsonl"
        if not index_path.exists():
            return mapping
        try:
            with index_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    session_id = str(
                        item.get("id") or item.get("thread_id") or item.get("session_id") or ""
                    )
                    title = clean_text(
                        item.get("thread_name") or item.get("title") or item.get("name"), 100
                    )
                    if session_id and title:
                        mapping[session_id] = title
        except OSError:
            pass
        return mapping

    def _peek_cwd(self, source_path: Path, provider: str) -> str:
        """Read only the small header of a transcript before full JSON parsing.

        A user can have gigabytes of transcripts across unrelated projects.
        Both Codex and Claude include cwd near the beginning of each JSONL, so
        this filter keeps first-run indexing proportional to this workspace.
        """
        try:
            with source_path.open("rb") as handle:
                # Codex puts cwd near the beginning of session_meta. Claude's
                # first event can be longer, but relevant Claude folders are
                # narrowed before this method is called.
                head = handle.read(64 * 1024 if provider == "codex" else 1024 * 1024)
            match = CWD_BYTES_RE.search(head)
            if match:
                return json.loads(b'"' + match.group(1) + b'"')
        except OSError:
            pass
        return ""

    def sync_conversations(self) -> dict[str, int]:
        updated = 0
        counts = {"codex_sessions": 0, "claude_sessions": 0}
        title_map = self._codex_title_map()
        roots: list[tuple[str, Path]] = [
            ("codex", self.user_home / ".codex" / "sessions"),
            ("codex", self.user_home / ".codex" / "archived_sessions"),
        ]
        claude_projects = self.user_home / ".claude" / "projects"
        if claude_projects.exists():
            # Claude encodes the workspace path in the project-directory name.
            # This avoids opening transcripts for every unrelated repository.
            workspace_marker = self.workspace.name.lower()
            matching_roots = [
                path for path in claude_projects.iterdir()
                if path.is_dir() and workspace_marker in path.name.lower()
            ]
            roots.extend(("claude", path) for path in matching_roots)
        for provider, root in roots:
            if not root.exists():
                continue
            for source_path in root.rglob("*.jsonl"):
                if self._unchanged(source_path):
                    existing = self.conn.execute(
                        "SELECT provider FROM sessions WHERE source_path=?",
                        (str(source_path),),
                    ).fetchone()
                    if existing:
                        counts[f"{existing['provider']}_sessions"] += 1
                    continue
                known_cwd = self._peek_cwd(source_path, provider)
                if not self._is_workspace(known_cwd):
                    continue
                parsed = (
                    self._parse_codex(source_path, title_map, known_cwd)
                    if provider == "codex"
                    else self._parse_claude(source_path, known_cwd)
                )
                if not parsed or not self._is_workspace(parsed.get("cwd")):
                    continue
                self._store_session(parsed)
                counts[f"{provider}_sessions"] += 1
                updated += 1
        return {**counts, "updated": updated}

    def _parse_codex(
        self, path: Path, title_map: dict[str, str], known_cwd: str = ""
    ) -> dict[str, Any] | None:
        uuid_match = UUID_RE.search(path.stem)
        session_id = uuid_match.group(0) if uuid_match else path.stem
        cwd = known_cwd
        started = ""
        ended = ""
        messages: list[dict[str, str]] = []
        try:
            with path.open("rb") as handle:
                for line in handle:
                    # Tool payloads and reasoning dominate transcript size. A
                    # byte-level gate avoids decoding/parsing those JSON rows.
                    if not RESPONSE_ITEM_BYTES_RE.search(line):
                        continue
                    if not MESSAGE_BYTES_RE.search(line):
                        continue
                    if not USER_ROLE_BYTES_RE.search(line) and not ASSISTANT_ROLE_BYTES_RE.search(line):
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    timestamp = str(item.get("timestamp") or "")
                    payload = item.get("payload") or {}
                    if item.get("type") != "response_item" or payload.get("type") != "message":
                        continue
                    role = payload.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    texts: list[str] = []
                    for part in payload.get("content") or []:
                        if not isinstance(part, dict) or part.get("type") not in {"input_text", "output_text"}:
                            continue
                        text = str(part.get("text") or "").strip()
                        if text.startswith(("<recommended_plugins>", "<environment_context>")):
                            continue
                        if text:
                            texts.append(text)
                    content = "\n\n".join(texts).strip()
                    if content:
                        messages.append({"role": role, "content": content, "created_at": timestamp})
                        started = started or timestamp
                        ended = timestamp or ended
        except OSError:
            return None
        if not messages:
            return None
        title = title_map.get(session_id) or clean_text(
            next((m["content"] for m in messages if m["role"] == "user"), "未命名对话"), 72
        )
        return self._session_payload("codex", session_id, path, cwd, started, ended, title, messages)

    def _parse_claude(self, path: Path, known_cwd: str = "") -> dict[str, Any] | None:
        session_id = path.stem
        cwd = known_cwd
        title = ""
        started = ""
        ended = ""
        messages: list[dict[str, str]] = []
        try:
            with path.open("rb") as handle:
                for line in handle:
                    is_title = bool(TITLE_EVENT_BYTES_RE.search(line))
                    is_plain_user = bool(USER_ROLE_BYTES_RE.search(line) and STRING_CONTENT_BYTES_RE.search(line))
                    is_text_assistant = bool(ASSISTANT_ROLE_BYTES_RE.search(line) and TEXT_PART_BYTES_RE.search(line))
                    if not (is_title or is_plain_user or is_text_assistant):
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    session_id = str(item.get("sessionId") or session_id)
                    cwd = str(item.get("cwd") or cwd)
                    timestamp = str(item.get("timestamp") or "")
                    if not started and timestamp:
                        started = timestamp
                    if item.get("type") in {"custom-title", "ai-title"}:
                        candidate = item.get("customTitle") or item.get("title") or item.get("aiTitle")
                        if candidate:
                            title = clean_text(str(candidate), 100)
                        continue
                    if item.get("type") not in {"user", "assistant"}:
                        continue
                    message = item.get("message") or {}
                    role = message.get("role") or item.get("type")
                    content_value = message.get("content")
                    texts: list[str] = []
                    if isinstance(content_value, str):
                        texts.append(content_value)
                    elif isinstance(content_value, list):
                        for part in content_value:
                            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                                texts.append(str(part["text"]))
                    content = "\n\n".join(texts).strip()
                    if content and not content.startswith("<system-reminder>"):
                        messages.append({"role": role, "content": content, "created_at": timestamp})
                        ended = timestamp or ended
        except OSError:
            return None
        if not messages:
            return None
        title = title or clean_text(
            next((m["content"] for m in messages if m["role"] == "user"), "未命名对话"), 72
        )
        unique_id = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
        return self._session_payload(
            "claude", f"{session_id}:{unique_id}", path, cwd, started, ended, title, messages
        )

    def _session_payload(
        self,
        provider: str,
        session_id: str,
        path: Path,
        cwd: str,
        started: str,
        ended: str,
        title: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        last_answer = next(
            (message["content"] for message in reversed(messages) if message["role"] == "assistant"),
            messages[-1]["content"],
        )
        return {
            "id": f"{provider}:{session_id}",
            "provider": provider,
            "title": clean_text(title, 100),
            "started_at": started,
            "ended_at": ended or started,
            "cwd": cwd,
            "source_path": str(path),
            "source_mtime": path.stat().st_mtime,
            "preview": clean_text(last_answer, 220),
            "messages": messages,
        }

    def _store_session(self, session: dict[str, Any]) -> None:
        existing = self.conn.execute(
            "SELECT note FROM sessions WHERE id=?", (session["id"],)
        ).fetchone()
        note = existing["note"] if existing else ""
        summary = conversation_summary(session["title"], session["messages"])
        tldr = summary["tldr"]
        keywords = extract_keywords(
            session["title"], summary["objective"], summary["result"], summary["approach"]
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO sessions(
                id, provider, title, started_at, ended_at, cwd, source_path,
                source_mtime, preview, message_count, note, indexed_at,
                tldr, summary_json, keywords_json, summary_version
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session["id"], session["provider"], session["title"],
                session["started_at"], session["ended_at"], session["cwd"],
                session["source_path"], session["source_mtime"], session["preview"],
                len(session["messages"]), note, now_iso(), tldr,
                json.dumps(summary, ensure_ascii=False),
                json.dumps(keywords, ensure_ascii=False), SUMMARY_VERSION,
            ),
        )
        self.conn.execute("DELETE FROM messages WHERE session_id=?", (session["id"],))
        self.conn.execute("DELETE FROM message_search WHERE session_id=?", (session["id"],))
        for ordinal, message in enumerate(session["messages"]):
            self.conn.execute(
                "INSERT INTO messages(session_id, ordinal, role, content, created_at) VALUES(?,?,?,?,?)",
                (session["id"], ordinal, message["role"], message["content"], message["created_at"]),
            )
            try:
                self.conn.execute(
                    "INSERT INTO message_search(session_id, content) VALUES(?,?)",
                    (session["id"], message["content"]),
                )
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    def sync_experiments(self) -> int:
        groups: dict[str, list[tuple[str, Path]]] = defaultdict(list)
        roots = {
            "source": self.workspace / "experiments",
            "script": self.workspace / "scripts",
            "launcher": self.workspace / "ops",
            "result": self.workspace / "results",
            "doc": self.workspace / "docs",
            "manifest": self.workspace / "manifests",
        }
        for kind, root in roots.items():
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
                    continue
                # Result files are often generic (metrics.json) inside an expXX
                # directory, so match the workspace-relative path, not only the
                # basename.
                relative_hint = str(path.relative_to(root)).replace(os.sep, "_")
                match = EXPERIMENT_RE.search("_" + relative_hint)
                if match:
                    groups[match.group(1).lower()].append((kind, path))

        for key, files in groups.items():
            files.sort(key=lambda pair: pair[1].stat().st_mtime, reverse=True)
            source_files = [path for kind, path in files if kind in {"source", "script"}]
            docs = [path for kind, path in files if kind == "doc"]
            results = [path for kind, path in files if kind == "result"]
            launchers = [path for kind, path in files if kind == "launcher"]
            settlement = next(
                (path for path in docs if re.search(r"settlement|closure|conclusion", path.name, re.I)),
                None,
            )
            prereg = next((path for path in docs if "prereg" in path.name.lower()), None)
            if settlement:
                status, status_label = "settled", "已结论"
            elif results:
                status, status_label = "results", "有结果"
            elif launchers:
                status, status_label = "configured", "已配置"
            elif prereg:
                status, status_label = "planned", "已预注册"
            else:
                status, status_label = "draft", "草稿"
            primary = next(
                (path for kind, path in files if kind == "source" and path.suffix.lower() == ".py"),
                source_files[0] if source_files else files[0][1],
            )
            raw_title = re.sub(r"(?i)^exp\d+[a-z0-9]*[_-]*", "", primary.stem)
            document_title = markdown_title(settlement or prereg) if (settlement or prereg) else ""
            document_title = re.sub(
                rf"(?i)^{re.escape(key)}\s*(?:settlement|preregistration|closure|conclusion)?\s*[:—-]*\s*",
                "",
                document_title,
            )
            title = clean_text(document_title, 100) or clean_text(
                raw_title.replace("_", " ").replace("-", " ").title(), 100
            ) or key.upper()
            summary_path = settlement or prereg or (docs[0] if docs else primary)
            fallback_summary = first_paragraph(summary_path)
            if not fallback_summary:
                fallback_summary = f"{len(source_files)} 个脚本，{len(results)} 个结果文件，{len(docs)} 份研究记录。"
            details = experiment_details(
                self.workspace, files, settlement, prereg, fallback_summary
            )
            summary = details["overview"] or fallback_summary
            metadata = {
                "recent_files": [str(path.relative_to(self.workspace)) for _, path in files[:8]],
                "latest_file": str(files[0][1].relative_to(self.workspace)),
                "details": details,
            }
            self.conn.execute(
                """
                INSERT INTO experiments(
                    key,title,status,status_label,summary,source_path,updated_at,
                    source_count,result_count,doc_count,launcher_count,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    title=excluded.title,status=excluded.status,status_label=excluded.status_label,
                    summary=excluded.summary,source_path=excluded.source_path,
                    updated_at=excluded.updated_at,source_count=excluded.source_count,
                    result_count=excluded.result_count,doc_count=excluded.doc_count,
                    launcher_count=excluded.launcher_count,metadata_json=excluded.metadata_json
                """,
                (
                    key.upper(), title, status, status_label, summary,
                    str(primary.relative_to(self.workspace)), ts_iso(files[0][1].stat().st_mtime),
                    len(source_files), len(results), len(docs), len(launchers),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
        stale_cache_keys = []
        for row in self.conn.execute("SELECT key,source_path FROM experiments"):
            source_path = str(row["source_path"] or "").replace("\\", "/").lower()
            if "/__pycache__/" in f"/{source_path}" or source_path.endswith((".pyc", ".pyo")):
                stale_cache_keys.append(row["key"])
        if stale_cache_keys:
            self.conn.executemany(
                "DELETE FROM experiments WHERE key=?",
                ((key,) for key in stale_cache_keys),
            )
        self.conn.commit()
        return len(groups)

    def _paper_key(
        self, doi: str = "", arxiv_id: str = "", title: str = "", pdf_hash: str = ""
    ) -> str:
        if doi:
            return f"doi:{normalize_doi(doi)}"
        if arxiv_id:
            return f"arxiv:{normalize_arxiv(arxiv_id)}"
        if pdf_hash:
            return f"sha256:{pdf_hash}"
        return f"title:{normalize_title(title)}"

    def sync_researched_papers(self) -> int:
        """Backfill literature already cited in project docs and research chats."""
        selected: dict[str, dict[str, Any]] = {}

        def collect(text: str) -> None:
            for candidate in paper_candidates_from_text(text):
                identity = (
                    f"doi:{candidate['doi']}" if candidate["doi"]
                    else f"arxiv:{candidate['arxiv_id']}" if candidate["arxiv_id"]
                    else f"url:{candidate['source_url']}"
                )
                previous = selected.get(identity)
                if previous is None or candidate["score"] > previous["score"]:
                    selected[identity] = candidate

        docs_root = self.workspace / "docs"
        if docs_root.exists():
            for path in sorted(docs_root.rglob("*.md")):
                try:
                    collect(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue

        markers = tuple(host for host in SCHOLARLY_HOSTS if "." in host)
        for row in self.conn.execute(
            "SELECT m.content,s.title FROM messages m JOIN sessions s ON s.id=m.session_id"
        ):
            if _research_kind(str(row["title"] or "")) not in {"paper_read", "novelty", "literature"}:
                continue
            content = str(row["content"] or "")
            lowered = content.lower()
            if any(marker in lowered for marker in markers) or "doi.org/" in lowered:
                collect(content)

        for candidate in sorted(selected.values(), key=lambda item: (-item["score"], item["title"].lower())):
            existing = self._find_existing_paper(
                candidate["doi"], candidate["arxiv_id"], "",
                candidate["title"], candidate["source_url"],
            )
            self.register_paper(
                title=candidate["title"], authors=candidate["authors"],
                year=candidate["year"], doi=candidate["doi"],
                arxiv_id=candidate["arxiv_id"], source_url=candidate["source_url"],
                status=existing["status"] if existing else "read",
                note=existing["note"] if existing else "",
            )
        return int(self.conn.execute("SELECT count(*) FROM papers").fetchone()[0])

    def _match_pdf_paper(self, path: Path) -> sqlite3.Row | None:
        stem = path.stem.lower().replace("-", "_")
        year_match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", stem)
        surname_match = re.match(r"([a-z][a-z'’]+)", stem)
        if not year_match or not surname_match:
            return None
        year = int(year_match.group(1))
        surname = surname_match.group(1)
        topic_tokens = {
            token for token in re.findall(r"[a-z]{4,}", stem)
            if token not in {surname, "paper", "source", "group"}
        }
        matches: list[tuple[int, sqlite3.Row]] = []
        for row in self.conn.execute("SELECT * FROM papers WHERE year=?", (year,)):
            authors = normalize_title(row["authors"])
            if surname not in authors:
                continue
            title_tokens = set(re.findall(r"[a-z]{4,}", str(row["title"] or "").lower()))
            matches.append((len(topic_tokens & title_tokens), row))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        if len(matches) == 1 or matches[0][0] > matches[1][0]:
            return matches[0][1]
        return None

    def sync_pdf_inbox(self) -> int:
        candidates: list[Path] = []
        for relative in ("literature", "papers", "data/external", "docs/literature"):
            root = self.workspace / relative
            if root.exists():
                candidates.extend(root.rglob("*.pdf"))
        for path in candidates:
            try:
                pdf_hash = sha256_file(path)
            except OSError:
                continue
            catalog = LOCAL_PDF_CATALOG.get(path.stem.lower())
            catalog_row = None
            if catalog:
                catalog_row = self._find_existing_paper(
                    "", catalog["arxiv_id"], "", catalog["title"],
                    f"https://arxiv.org/abs/{catalog['arxiv_id']}",
                )
                if catalog_row:
                    self.conn.execute(
                        "UPDATE papers SET title=?,authors=?,year=?,source_url=?,updated_at=? WHERE id=?",
                        (
                            catalog["title"], catalog["authors"], catalog["year"],
                            f"https://arxiv.org/abs/{catalog['arxiv_id']}", now_iso(), catalog_row["id"],
                        ),
                    )
                else:
                    item = self.register_paper(
                        title=catalog["title"], authors=catalog["authors"], year=catalog["year"],
                        arxiv_id=catalog["arxiv_id"],
                        source_url=f"https://arxiv.org/abs/{catalog['arxiv_id']}", status="read",
                    )
                    catalog_row = self.conn.execute(
                        "SELECT * FROM papers WHERE id=?", (item["id"],)
                    ).fetchone()
            existing = self.conn.execute(
                "SELECT * FROM papers WHERE pdf_hash=? OR pdf_path=?",
                (pdf_hash, str(path.resolve())),
            ).fetchone()
            if catalog_row and existing and catalog_row["id"] != existing["id"]:
                self.conn.execute(
                    "UPDATE papers SET pdf_path='',pdf_hash='',file_updated_at=NULL WHERE id=?",
                    (existing["id"],),
                )
                if (
                    not existing["doi"] and not existing["arxiv_id"] and not existing["source_url"]
                    and normalize_title(existing["title"]) == normalize_title(path.stem)
                ):
                    self.conn.execute("DELETE FROM papers WHERE id=?", (existing["id"],))
            existing = catalog_row or existing or self._match_pdf_paper(path)
            if existing:
                self.conn.execute(
                    "UPDATE papers SET pdf_path=?,pdf_hash=?,file_updated_at=?,updated_at=? WHERE id=?",
                    (
                        str(path.resolve()), pdf_hash, ts_iso(path.stat().st_mtime),
                        now_iso(), existing["id"],
                    ),
                )
                continue
            self.register_paper(
                title=path.stem.replace("_", " "), pdf_path=str(path), pdf_hash=pdf_hash
            )
        self.conn.commit()
        return int(self.conn.execute("SELECT count(*) FROM papers").fetchone()[0])

    def _find_existing_paper(
        self, doi: str, arxiv_id: str, pdf_hash: str, title: str, source_url: str = ""
    ) -> sqlite3.Row | None:
        clauses: list[str] = []
        values: list[str] = []
        for column, value in (
            ("doi", doi), ("arxiv_id", arxiv_id), ("pdf_hash", pdf_hash),
            ("source_url", normalize_paper_url(source_url)),
        ):
            if value:
                clauses.append(f"{column}=?")
                values.append(value)
        if clauses:
            row = self.conn.execute(
                "SELECT * FROM papers WHERE " + " OR ".join(clauses) + " LIMIT 1", values
            ).fetchone()
            if row:
                return row
        normalized = normalize_title(title)
        if normalized:
            for row in self.conn.execute("SELECT * FROM papers"):
                if normalize_title(row["title"]) == normalized:
                    return row
        return None

    def register_paper(
        self,
        *,
        title: str = "",
        doi: str = "",
        arxiv_id: str = "",
        pdf_path: str = "",
        pdf_hash: str = "",
        source_url: str = "",
        authors: str = "",
        year: int | None = None,
        abstract: str = "",
        status: str = "inbox",
        note: str = "",
        refresh: bool = False,
    ) -> dict[str, Any]:
        doi = normalize_doi(doi or source_url)
        arxiv_id = normalize_arxiv(arxiv_id or source_url)
        resolved_pdf = ""
        if pdf_path:
            candidate = Path(pdf_path).expanduser()
            if not candidate.is_absolute():
                candidate = self.workspace / candidate
            candidate = candidate.resolve()
            if not candidate.exists() or candidate.suffix.lower() != ".pdf":
                raise ValueError("PDF 路径不存在，或文件不是 PDF。")
            resolved_pdf = str(candidate)
            pdf_hash = pdf_hash or sha256_file(candidate)
        metadata: dict[str, Any] = {}
        if refresh and doi:
            metadata = self.fetch_crossref(doi)
        elif refresh and arxiv_id:
            metadata = self.fetch_arxiv(arxiv_id)
        title = clean_text(metadata.get("title") or title or (Path(resolved_pdf).stem if resolved_pdf else "未命名文献"), 300)
        authors = clean_text(metadata.get("authors") or authors, 500)
        year = metadata.get("year") or year
        abstract = clean_text(metadata.get("abstract") or abstract, 5000)
        source_url = str(metadata.get("source_url") or source_url or (f"https://doi.org/{doi}" if doi else ""))
        source_url = normalize_paper_url(source_url)
        existing = self._find_existing_paper(doi, arxiv_id, pdf_hash, title, source_url)
        timestamp = now_iso()
        metadata_updated = timestamp if metadata else None
        file_updated = ts_iso(Path(resolved_pdf).stat().st_mtime) if resolved_pdf else None
        if existing:
            paper_id = existing["id"]
            canonical_key = self._paper_key(
                doi or existing["doi"], arxiv_id or existing["arxiv_id"],
                title or existing["title"], pdf_hash or existing["pdf_hash"],
            )
            self.conn.execute(
                """
                UPDATE papers SET canonical_key=?, title=?, authors=?, year=?, doi=?, arxiv_id=?,
                    pdf_path=?, pdf_hash=?, source_url=?, abstract=?, status=?, note=?,
                    metadata_updated_at=COALESCE(?, metadata_updated_at),
                    file_updated_at=COALESCE(?, file_updated_at), updated_at=?
                WHERE id=?
                """,
                (
                    canonical_key, title or existing["title"], authors or existing["authors"],
                    year or existing["year"], doi or existing["doi"], arxiv_id or existing["arxiv_id"],
                    resolved_pdf or existing["pdf_path"], pdf_hash or existing["pdf_hash"],
                    source_url or existing["source_url"], abstract or existing["abstract"],
                    status or existing["status"], note or existing["note"], metadata_updated,
                    file_updated, timestamp, paper_id,
                ),
            )
        else:
            canonical_key = self._paper_key(doi, arxiv_id, title, pdf_hash)
            cursor = self.conn.execute(
                """
                INSERT INTO papers(
                    canonical_key,title,authors,year,doi,arxiv_id,pdf_path,pdf_hash,
                    source_url,abstract,status,note,metadata_updated_at,file_updated_at,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    canonical_key, title, authors, year, doi, arxiv_id, resolved_pdf, pdf_hash,
                    source_url, abstract, status, note, metadata_updated, file_updated,
                    timestamp, timestamp,
                ),
            )
            paper_id = cursor.lastrowid
        self.conn.commit()
        return self.get_paper(int(paper_id))

    def fetch_crossref(self, doi: str) -> dict[str, Any]:
        doi = normalize_doi(doi)
        if not doi:
            raise ValueError("没有识别出有效 DOI。")
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
        request = urllib.request.Request(
            url, headers={"User-Agent": "JSpace-Research-Workbench/0.1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                message = json.load(response).get("message", {})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ValueError(f"Crossref 更新失败：{error}") from error
        authors = []
        for author in message.get("author") or []:
            name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
            if name:
                authors.append(name)
        date_parts = ((message.get("published") or message.get("issued") or {}).get("date-parts") or [[]])
        year = date_parts[0][0] if date_parts and date_parts[0] else None
        abstract = html.unescape(TAG_RE.sub(" ", message.get("abstract") or ""))
        return {
            "title": (message.get("title") or [""])[0],
            "authors": ", ".join(authors),
            "year": year,
            "abstract": abstract,
            "source_url": message.get("URL") or f"https://doi.org/{doi}",
        }

    def fetch_arxiv(self, arxiv_id: str) -> dict[str, Any]:
        arxiv_id = normalize_arxiv(arxiv_id)
        if not arxiv_id:
            raise ValueError("没有识别出有效 arXiv ID。")
        url = "https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv_id)
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                root = ET.fromstring(response.read())
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as error:
            raise ValueError(f"arXiv 更新失败：{error}") from error
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            raise ValueError("arXiv 没有返回该文献。")
        authors = [
            clean_text(node.findtext("atom:name", default="", namespaces=ns))
            for node in entry.findall("atom:author", ns)
        ]
        published = entry.findtext("atom:published", default="", namespaces=ns)
        return {
            "title": clean_text(entry.findtext("atom:title", default="", namespaces=ns)),
            "authors": ", ".join(filter(None, authors)),
            "year": int(published[:4]) if published[:4].isdigit() else None,
            "abstract": clean_text(entry.findtext("atom:summary", default="", namespaces=ns)),
            "source_url": f"https://arxiv.org/abs/{arxiv_id}",
        }

    def fetch_arxiv_batch(self, arxiv_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = [normalize_arxiv(value) for value in arxiv_ids]
        ids = list(dict.fromkeys(value for value in ids if value))
        if not ids:
            return {}
        query = urllib.parse.urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
        try:
            with urllib.request.urlopen("https://export.arxiv.org/api/query?" + query, timeout=30) as response:
                root = ET.fromstring(response.read())
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as error:
            raise ValueError(f"arXiv 批量更新失败：{error}") from error
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        output: dict[str, dict[str, Any]] = {}
        for entry in root.findall("atom:entry", ns):
            identity = normalize_arxiv(entry.findtext("atom:id", default="", namespaces=ns))
            if not identity:
                continue
            authors = [
                clean_text(node.findtext("atom:name", default="", namespaces=ns))
                for node in entry.findall("atom:author", ns)
            ]
            published = entry.findtext("atom:published", default="", namespaces=ns)
            output[identity] = {
                "title": clean_text(entry.findtext("atom:title", default="", namespaces=ns), 300),
                "authors": ", ".join(filter(None, authors)),
                "year": int(published[:4]) if published[:4].isdigit() else None,
                "abstract": clean_text(entry.findtext("atom:summary", default="", namespaces=ns), 5000),
                "source_url": f"https://arxiv.org/abs/{identity}",
            }
        return output

    def refresh_arxiv_papers(self, minimum_age_days: int = 7, limit: int = 500) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=minimum_age_days)).isoformat()
        rows = self.conn.execute(
            """
            SELECT arxiv_id FROM papers
            WHERE arxiv_id != '' AND (metadata_updated_at IS NULL OR metadata_updated_at < ?)
              AND (title LIKE 'arXiv %' OR authors='' OR abstract='')
            ORDER BY title LIKE 'arXiv %' DESC, metadata_updated_at IS NULL DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        refreshed = 0
        attempted_at = now_iso()
        ids = [row["arxiv_id"] for row in rows]
        for offset in range(0, len(ids), 80):
            batch = ids[offset: offset + 80]
            try:
                metadata = self.fetch_arxiv_batch(batch)
            except ValueError:
                continue
            for arxiv_id in batch:
                item = metadata.get(arxiv_id)
                if item:
                    self.conn.execute(
                        """
                        UPDATE papers SET title=?,authors=?,year=?,abstract=?,source_url=?,
                            metadata_updated_at=?,updated_at=? WHERE arxiv_id=?
                        """,
                        (
                            item["title"], item["authors"], item["year"], item["abstract"],
                            item["source_url"], attempted_at, attempted_at, arxiv_id,
                        ),
                    )
                    refreshed += 1
                else:
                    self.conn.execute(
                        "UPDATE papers SET metadata_updated_at=? WHERE arxiv_id=?",
                        (attempted_at, arxiv_id),
                    )
            self.conn.commit()
        return refreshed

    def dedupe_papers(self) -> int:
        """Merge venue/arXiv duplicates after metadata resolution, preserving local PDFs and notes."""
        groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in self.conn.execute("SELECT * FROM papers"):
            key = normalize_title(row["title"])
            if len(key) >= 12 and not str(row["title"]).startswith(("arXiv ", "OpenReview ")):
                groups[key].append(row)
        removed = 0
        status_rank = {"inbox": 0, "reading": 1, "read": 2, "cited": 3}
        for rows in groups.values():
            if len(rows) < 2:
                continue
            rows.sort(
                key=lambda row: (
                    bool(row["pdf_path"]), bool(row["doi"]), bool(row["arxiv_id"]),
                    bool(row["abstract"]), bool(row["authors"]), len(row["title"]),
                ),
                reverse=True,
            )
            survivor = rows[0]
            merged = dict(survivor)
            for row in rows[1:]:
                for field in (
                    "authors", "year", "doi", "arxiv_id", "pdf_path", "pdf_hash",
                    "source_url", "abstract", "note", "metadata_updated_at", "file_updated_at",
                ):
                    if not merged.get(field) and row[field]:
                        merged[field] = row[field]
                if status_rank.get(row["status"], 0) > status_rank.get(merged["status"], 0):
                    merged["status"] = row["status"]
            duplicate_ids = [row["id"] for row in rows[1:]]
            self.conn.executemany("DELETE FROM papers WHERE id=?", ((paper_id,) for paper_id in duplicate_ids))
            canonical_key = self._paper_key(
                merged.get("doi", ""), merged.get("arxiv_id", ""), merged["title"],
                merged.get("pdf_hash", ""),
            )
            self.conn.execute(
                """
                UPDATE papers SET canonical_key=?,authors=?,year=?,doi=?,arxiv_id=?,pdf_path=?,
                    pdf_hash=?,source_url=?,abstract=?,status=?,note=?,metadata_updated_at=?,
                    file_updated_at=?,updated_at=? WHERE id=?
                """,
                (
                    canonical_key, merged.get("authors", ""), merged.get("year"),
                    merged.get("doi", ""), merged.get("arxiv_id", ""),
                    merged.get("pdf_path", ""), merged.get("pdf_hash", ""),
                    merged.get("source_url", ""), merged.get("abstract", ""),
                    merged.get("status", "read"), merged.get("note", ""),
                    merged.get("metadata_updated_at"), merged.get("file_updated_at"),
                    now_iso(), survivor["id"],
                ),
            )
            removed += len(duplicate_ids)
        self.conn.commit()
        return removed

    def refresh_due_papers(self, minimum_age_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=minimum_age_days)).isoformat()
        rows = self.conn.execute(
            """
            SELECT * FROM papers
            WHERE (doi != '' OR arxiv_id != '')
              AND (metadata_updated_at IS NULL OR metadata_updated_at < ?)
            ORDER BY metadata_updated_at IS NULL DESC LIMIT 20
            """,
            (cutoff,),
        ).fetchall()
        refreshed = 0
        for row in rows:
            try:
                self.register_paper(
                    title=row["title"], doi=row["doi"], arxiv_id=row["arxiv_id"],
                    pdf_path=row["pdf_path"], source_url=row["source_url"],
                    authors=row["authors"], year=row["year"], abstract=row["abstract"],
                    status=row["status"], note=row["note"], refresh=True,
                )
                refreshed += 1
            except ValueError:
                continue
        return refreshed

    @staticmethod
    def _legacy_experiment_entries(body: str) -> list[dict[str, str]]:
        """Recover experiment bullets from the pre-TLDR digest format."""
        entries: list[dict[str, str]] = []
        in_experiments = False
        for raw_line in (body or "").splitlines():
            line = raw_line.strip()
            if line in {"实验推进：", "实验推进:", "## 实验"} or line.startswith("## 实验"):
                in_experiments = True
                continue
            if line.startswith("## "):
                in_experiments = False
            if not in_experiments:
                continue
            match = EXPERIMENT_ID_RE.search(line.replace("**", ""))
            if not match:
                continue
            key = re.sub(r"\s+", "", match.group(0)).upper()
            remainder = clean_text(line.replace("**", "").lstrip("•-* "))
            parts = [clean_text(part) for part in remainder.split("·") if clean_text(part)]
            entries.append(
                {
                    "key": key,
                    "status_label": parts[1] if len(parts) >= 3 else "历史记录",
                    "title": parts[-1] if len(parts) >= 2 else remainder,
                }
            )
        unique: dict[str, dict[str, str]] = {}
        for entry in entries:
            unique.setdefault(entry["key"], entry)
        return list(unique.values())

    @staticmethod
    def _experiment_result(item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        if not metadata and item.get("metadata_json"):
            try:
                metadata = json.loads(item.get("metadata_json") or "{}")
            except json.JSONDecodeError:
                metadata = {}
        sections = metadata.get("details", {}).get("sections", [])
        result = next(
            (section.get("body") for section in sections if section.get("label") == "结果与结论"),
            "",
        )
        if result:
            return plain_excerpt(str(result), 200)
        if item.get("summary"):
            return plain_excerpt(str(item["summary"]), 200)
        return f"{item.get('key', '实验')} 当前状态：{item.get('status_label', '待整理')}。"

    def backfill_summaries(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT id,title FROM sessions WHERE summary_version<? OR tldr=''",
            (SUMMARY_VERSION,),
        ).fetchall()
        for row in rows:
            messages = self._rows(
                self.conn.execute(
                    "SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY ordinal",
                    (row["id"],),
                ).fetchall()
            )
            summary = conversation_summary(row["title"], messages)
            tldr = summary["tldr"]
            keywords = extract_keywords(
                row["title"], summary["objective"], summary["result"], summary["approach"]
            )
            self.conn.execute(
                "UPDATE sessions SET tldr=?,summary_json=?,keywords_json=?,summary_version=? WHERE id=?",
                (
                    tldr, json.dumps(summary, ensure_ascii=False),
                    json.dumps(keywords, ensure_ascii=False), SUMMARY_VERSION, row["id"],
                ),
            )
        self.conn.commit()

        days = {date.today().isoformat()}
        for table, column in (
            ("sessions", "ended_at"),
            ("experiments", "updated_at"),
            ("papers", "updated_at"),
        ):
            days.update(
                row[0]
                for row in self.conn.execute(
                    f"SELECT DISTINCT substr({column},1,10) FROM {table} WHERE {column}<>''"
                )
                if row[0] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0])
            )
        days.update(row[0] for row in self.conn.execute("SELECT day FROM daily_digests"))
        for digest_day in sorted(days):
            self.build_digest(digest_day)
        return {"session_tldrs_backfilled": len(rows), "daily_tldrs_built": len(days)}

    def build_digest(self, day: str) -> dict[str, Any]:
        sessions = self._rows(
            self.conn.execute(
                "SELECT id,provider,title,tldr,summary_json,keywords_json,message_count,ended_at FROM sessions "
                "WHERE substr(ended_at,1,10)=? ORDER BY ended_at DESC",
                (day,),
            ).fetchall()
        )
        experiments = self._rows(
            self.conn.execute(
                "SELECT key,title,status_label,summary,metadata_json,updated_at FROM experiments "
                "WHERE substr(updated_at,1,10)=? ORDER BY updated_at DESC",
                (day,),
            ).fetchall()
        )
        papers = self._rows(
            self.conn.execute(
                "SELECT title,abstract,note,updated_at FROM papers WHERE substr(updated_at,1,10)=? "
                "ORDER BY updated_at DESC",
                (day,),
            ).fetchall()
        )
        previous = self.conn.execute(
            "SELECT auto_body,stats_json FROM daily_digests WHERE day=?", (day,)
        ).fetchone()
        legacy_entries = self._legacy_experiment_entries(previous["auto_body"] if previous else "")
        known_keys = {item["key"] for item in experiments}
        experiments.extend(item for item in legacy_entries if item["key"] not in known_keys)
        try:
            legacy_stats = json.loads(previous["stats_json"] or "{}") if previous else {}
        except json.JSONDecodeError:
            legacy_stats = {}

        keyword_scores: dict[str, tuple[int, str]] = {}
        for item in sessions:
            for position, keyword in enumerate(item.get("keywords", [])):
                keyword = _plain_keyword(keyword)
                if not keyword:
                    continue
                key = keyword.lower()
                score, _ = keyword_scores.get(key, (0, keyword))
                keyword_scores[key] = (score + max(10 - position, 2), keyword)
        for item in experiments:
            key = item["key"].lower()
            keyword_scores[key] = (120, item["key"])
            for position, keyword in enumerate(extract_keywords(item["title"], limit=4)):
                normalized = keyword.lower()
                score, _ = keyword_scores.get(normalized, (0, keyword))
                keyword_scores[normalized] = (score + max(8 - position, 2), keyword)
        for item in papers:
            for keyword in extract_keywords(item["title"], limit=4):
                normalized = keyword.lower()
                score, _ = keyword_scores.get(normalized, (0, keyword))
                keyword_scores[normalized] = (score + 6, keyword)
        keywords = [
            display for _, display in sorted(keyword_scores.values(), key=lambda value: (-value[0], value[1].lower()))[:12]
        ]
        experiment_count = max(len(experiments), int(legacy_stats.get("experiments", 0) or 0))
        stats = {
            "sessions": len(sessions),
            "experiments": experiment_count,
            "papers": len(papers),
        }
        experiment_items: list[dict[str, Any]] = []
        for item in experiments[:10]:
            raw_result = self._experiment_result(item)
            experiment_items.append(
                {
                    "key": item["key"],
                    "title": _plain_experiment_topic(item["title"], item["key"]),
                    "original_title": item["title"],
                    "status": item.get("status_label", "历史记录"),
                    "result": _plain_experiment_result(item, raw_result),
                    "updated_at": item.get("updated_at", ""),
                }
            )

        research_items = _daily_research_items(sessions)
        result_items: list[dict[str, Any]] = []
        for item in experiment_items:
            if any(cue in item["result"] for cue in ("尚未", "仍在整理", "还没有")):
                continue
            result_items.append(
                {
                    "session_id": "",
                    "title": f"{item['key']}：{item['title']}",
                    "provider": "local",
                    "result": item["result"],
                    "next_step": "未明确记录下一步。",
                    "experiment_ids": [item["key"]],
                }
            )
        for item in research_items:
            if item["kind"] not in {"novelty", "paper_read"}:
                continue
            result_items.append(
                {
                    "session_id": item["session_id"],
                    "title": item["title"],
                    "provider": item["provider"],
                    "result": item["approach"],
                    "next_step": (
                        "继续核查筛出的相近论文，并补充必要的引用和对照。"
                        if item["kind"] == "novelty"
                        else "未明确记录下一步。"
                    ),
                    "experiment_ids": [],
                }
            )
        paper_items = [
            {
                "title": item["title"],
                "summary": plain_excerpt(item.get("note") or item.get("abstract") or "已登记文献", 220),
            }
            for item in papers[:8]
        ]
        topics: list[str] = []
        for item in experiment_items:
            if item["title"] not in topics:
                topics.append(item["title"])
            if len(topics) >= 3:
                break

        research_kinds = {item["kind"] for item in research_items}
        if experiment_count:
            headline = (
                f"今天的主线是围绕{_join_chinese(topics)}推进实验"
                if topics
                else "今天的主线是推进现有实验"
            )
            if research_items or papers:
                headline += "，并同步核对相关文献和已有证据。"
            else:
                headline += "，把当天形成的结果和待验证问题整理清楚。"
        elif research_items:
            headline = "今天的主线是整理相关论文和已有证据，明确当前判断及下一步要核查的问题。"
        elif papers:
            headline = f"今天的主线是整理新登记或更新的 {len(papers)} 篇文献，并把它们纳入本地研究索引。"
        else:
            headline = "今天没有新的实验或独立调研变动，日报保留当天索引以便后续追踪。"

        experiment_detail_parts: list[str] = []
        for item in experiment_items[:4]:
            result_clause = item["result"].rstrip("。")
            result_clause = result_clause.replace("实验已经完成，", "")
            result_clause = result_clause.replace("实验已经完成并形成结论", "已经形成结论")
            result_clause = result_clause.replace("实验已经配置好，", "已经配置好，")
            result_clause = result_clause.replace("实验已有记录更新，但", "已有记录更新，但")
            result_clause = result_clause.replace("实验有新的进展，", "有新的进展，")
            topic_separator = " " if re.match(r"[A-Za-z0-9]", item["title"]) else ""
            experiment_detail_parts.append(
                f"{item['key']} 检查{topic_separator}{item['title']}，{result_clause}"
            )
        experiment_text = f"推进 {experiment_count} 项实验。"
        if experiment_detail_parts:
            experiment_text += "；".join(experiment_detail_parts) + "。"
        hidden_experiment_count = max(experiment_count - len(experiment_detail_parts), 0)
        if hidden_experiment_count:
            experiment_text += f"另有 {hidden_experiment_count} 项变动保留在下方实验记录中。"
        if not experiment_count:
            experiment_text = "当天没有新的实验变动。"

        supported_ids: list[str] = []
        mixed_ids: list[str] = []
        negative_ids: list[str] = []
        pending_ids: list[str] = []
        settled_ids: list[str] = []
        for item in experiment_items:
            result = item["result"]
            key = item["key"]
            if any(cue in result for cue in ("尚未", "仍在整理", "还没有")):
                pending_ids.append(key)
            elif "没有支持" in result:
                negative_ids.append(key)
            elif "部分支持" in result or "边界" in result or "反例" in result:
                mixed_ids.append(key)
            elif "支持原来的判断" in result:
                supported_ids.append(key)
            else:
                settled_ids.append(key)

        result_parts: list[str] = []
        if supported_ids:
            result_parts.append(f"{'、'.join(supported_ids)} 支持原来的判断")
        if mixed_ids:
            result_parts.append(
                f"{'、'.join(mixed_ids)} 只部分支持，并暴露了需要继续解释的边界条件"
            )
        if negative_ids:
            result_parts.append(f"{'、'.join(negative_ids)} 没有支持原来的判断")
        if settled_ids:
            result_parts.append(f"{'、'.join(settled_ids)} 已经形成结果或结论")
        if pending_ids:
            result_parts.append(f"{'、'.join(pending_ids)} 仍在配置、运行或整理结果")
        result_text = "；".join(result_parts) + ("。" if result_parts else "")
        if not result_text:
            result_text = "当天记录中还没有形成新的实验结论。"

        activity_parts: list[str] = []
        research_evidence: list[str] = []
        for item in research_items:
            if item["kind"] == "paper_read":
                activity_parts.append(f"{item['count']} 组论文精读")
            elif item["kind"] == "novelty":
                activity_parts.append(f"{item['count']} 次相关工作与新颖性扫描")
            elif item["kind"] == "literature":
                activity_parts.append(f"{item['count']} 组文献整理")
            else:
                activity_parts.append(f"{item['count']} 项研究问题梳理")
            if item["approach"] not in research_evidence:
                research_evidence.append(item["approach"])
        if activity_parts:
            research_text = f"完成了 {'、'.join(activity_parts)}。" + "".join(research_evidence)
        elif papers:
            research_text = f"登记或更新了 {len(papers)} 篇文献；当天没有单独记录论文精读或新颖性扫描。"
        else:
            research_text = "当天没有独立的文献调研记录。"

        next_parts: list[str] = []
        if pending_ids:
            displayed_pending = "、".join(pending_ids[:3])
            suffix = " 等" if len(pending_ids) > 3 else ""
            next_parts.append(f"优先结算 {displayed_pending}{suffix}实验，确认它们的最终结果")
        if mixed_ids:
            next_parts.append(f"复核 {'、'.join(mixed_ids[:3])} 暴露的边界条件")
        if negative_ids:
            next_parts.append(f"检查 {'、'.join(negative_ids[:3])} 的实验设定或替代解释")
        if "novelty" in research_kinds:
            next_parts.append("继续核查筛出的相近论文，并把引用和对照补齐")
        elif "paper_read" in research_kinds:
            next_parts.append("把精读中发现的证据差异转成下一轮可验证的问题")
        elif papers:
            next_parts.append("继续阅读新登记的文献，并记录与当前实验最相关的证据")
        if not next_parts and experiment_count:
            next_parts.append("围绕已经形成的结论安排下一轮复核")
        if not next_parts:
            next_parts.append("等待新的实验或调研记录后再更新判断")
        next_text = "；".join(next_parts) + "。"

        tldr = "\n\n".join(
            [
                headline,
                "\n".join(
                    [
                        f"- **实验**：{experiment_text}",
                        f"- **结果**：{result_text}",
                        f"- **调研**：{research_text}",
                        f"- **下一步**：{next_text}",
                    ]
                ),
            ]
        )

        sections = {
            "experiments": experiment_items,
            "research": research_items[:12],
            "results": result_items[:10],
            "papers": paper_items,
        }
        lines = ["## 每日 TLDR", tldr, "", "## 实验"]
        if experiment_items:
            for item in experiment_items[:8]:
                lines.append(
                    f"- **{item['key']}** · {item['title']}：{item['result']}"
                )
            if experiment_count > len(experiment_items[:8]):
                lines.append(f"- 另有 {experiment_count - len(experiment_items[:8])} 项实验变动保留在历史统计中。")
        else:
            lines.append("- 当日未记录实验变动。")

        lines.extend(["", "## 调研"])
        if research_items:
            for item in research_items[:8]:
                lines.append(f"- **{item['title']}**：{item['objective']} {item['approach']}")
        if papers:
            for item in papers[:5]:
                note = plain_excerpt(item.get("note") or item.get("abstract") or "已登记文献", 160)
                lines.append(f"- **文献：{item['title']}** — {note}")
        if not sessions and not papers:
            lines.append("- 当日未记录独立调研活动。")

        lines.extend(["", "## 结果"])
        result_lines = [f"- **{item['title']}**：{item['result']}" for item in result_items[:8]]
        lines.extend(result_lines or ["- 当日记录中尚未形成明确结果。"])

        lines.extend(["", "## 关键词"])
        lines.append("- " + " · ".join(f"`{keyword}`" for keyword in keywords) if keywords else "- 暂无关键词。")
        self.conn.execute(
            """
            INSERT INTO daily_digests(
                day,tldr,auto_body,sections_json,keywords_json,stats_json,summary_version,generated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET tldr=excluded.tldr,auto_body=excluded.auto_body,
                sections_json=excluded.sections_json,keywords_json=excluded.keywords_json,
                stats_json=excluded.stats_json,
                summary_version=excluded.summary_version,generated_at=excluded.generated_at
            """,
            (
                day, tldr, "\n".join(lines), json.dumps(sections, ensure_ascii=False),
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(stats, ensure_ascii=False), DIGEST_VERSION, now_iso(),
            ),
        )
        self.conn.commit()
        return self.get_digest(day)

    @staticmethod
    def _rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if "metadata_json" in item:
                try:
                    item["metadata"] = json.loads(item.pop("metadata_json"))
                except json.JSONDecodeError:
                    item["metadata"] = {}
            for source, target in (("summary_json", "summary"), ("sections_json", "sections")):
                if source in item:
                    try:
                        item[target] = json.loads(item.pop(source) or "{}")
                    except json.JSONDecodeError:
                        item[target] = {}
            if "keywords_json" in item:
                item["keywords"] = parse_keywords(item.pop("keywords_json"))
            result.append(item)
        return result

    def get_digest(self, day: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM daily_digests WHERE day=?", (day,)).fetchone()
        if not row or int(row["summary_version"] or 0) < DIGEST_VERSION:
            return self.build_digest(day)
        item = dict(row)
        item["stats"] = json.loads(item.pop("stats_json") or "{}")
        try:
            item["sections"] = json.loads(item.pop("sections_json", "{}") or "{}")
        except json.JSONDecodeError:
            item["sections"] = {}
        item["keywords"] = parse_keywords(item.pop("keywords_json", "[]"))
        return item

    def dashboard(self, day: str | None = None) -> dict[str, Any]:
        day = day or date.today().isoformat()
        last_sync = self.conn.execute(
            "SELECT value FROM app_meta WHERE key='last_sync'"
        ).fetchone()
        counts = {
            "sessions": self.conn.execute("SELECT count(*) FROM sessions").fetchone()[0],
            "experiments": self.conn.execute("SELECT count(*) FROM experiments").fetchone()[0],
            "papers": self.conn.execute("SELECT count(*) FROM papers").fetchone()[0],
            "notes_needed": self.conn.execute(
                "SELECT count(*) FROM sessions WHERE note=''"
            ).fetchone()[0],
        }
        key_docs = []
        for name in (
            "experiment_ledger.md", "novelty_register.md", "related_work.md", "research_plan.md"
        ):
            path = self.workspace / "docs" / name
            if path.exists():
                key_docs.append(
                    {"name": name, "path": str(path.relative_to(self.workspace)), "updated_at": ts_iso(path.stat().st_mtime)}
                )
        return {
            "day": day,
            "last_sync": last_sync[0] if last_sync else None,
            "counts": counts,
            "digest": self.get_digest(day),
            "recent_sessions": self.list_sessions(limit=6),
            "recent_experiments": self.list_experiments(limit=6),
            "recent_papers": self.list_papers(limit=5),
            "key_docs": key_docs,
        }

    def list_sessions(
        self, query: str = "", provider: str = "", limit: int = 80
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if provider in {"codex", "claude"}:
            clauses.append("provider=?")
            values.append(provider)
        if query:
            like = f"%{query}%"
            ids: list[str] = []
            try:
                ids = [
                    row[0]
                    for row in self.conn.execute(
                        "SELECT DISTINCT session_id FROM message_search WHERE message_search MATCH ? LIMIT 250",
                        (query,),
                    )
                ]
            except sqlite3.OperationalError:
                pass
            search = "(title LIKE ? OR preview LIKE ? OR tldr LIKE ? OR summary_json LIKE ? OR keywords_json LIKE ?"
            values.extend([like, like, like, like, like])
            if ids:
                search += " OR id IN (" + ",".join("?" for _ in ids) + ")"
                values.extend(ids)
            clauses.append(search + ")")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        return self._rows(
            self.conn.execute(
                "SELECT id,provider,title,started_at,ended_at,preview,message_count,note,"
                "tldr,summary_json,keywords_json,summary_version "
                f"FROM sessions{where} ORDER BY COALESCE(ended_at,started_at) DESC LIMIT ?",
                values,
            ).fetchall()
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["keywords"] = parse_keywords(item.pop("keywords_json", "[]"))
        try:
            item["summary"] = json.loads(item.pop("summary_json", "{}") or "{}")
        except json.JSONDecodeError:
            item["summary"] = {}
        item["messages"] = self._rows(
            self.conn.execute(
                "SELECT ordinal,role,content,created_at FROM messages WHERE session_id=? ORDER BY ordinal",
                (session_id,),
            ).fetchall()
        )
        return item

    def list_experiments(self, query: str = "", status: str = "", limit: int = 120) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if query:
            clauses.append("(key LIKE ? OR title LIKE ? OR summary LIKE ? OR note LIKE ?)")
            values.extend([f"%{query}%"] * 4)
        if status:
            clauses.append("status=?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        return self._rows(
            self.conn.execute(
                f"SELECT * FROM experiments{where} ORDER BY updated_at DESC LIMIT ?", values
            ).fetchall()
        )

    def list_papers(self, query: str = "", status: str = "", limit: int = 5000) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if query:
            clauses.append("(title LIKE ? OR authors LIKE ? OR doi LIKE ? OR note LIKE ?)")
            values.extend([f"%{query}%"] * 4)
        if status:
            clauses.append("status=?")
            values.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        return self._rows(
            self.conn.execute(
                "SELECT id,title,authors,year,doi,arxiv_id,pdf_path,source_url,status,note,"
                "metadata_updated_at,file_updated_at,created_at,updated_at "
                f"FROM papers{where} ORDER BY updated_at DESC LIMIT ?", values
            ).fetchall()
        )

    def get_paper(self, paper_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        if not row:
            raise KeyError(paper_id)
        return dict(row)

    def update_note(self, table: str, identifier: Any, note: str, status: str | None = None) -> None:
        if table == "papers":
            if status:
                self.conn.execute(
                    "UPDATE papers SET note=?,status=?,updated_at=? WHERE id=?",
                    (note, status, now_iso(), identifier),
                )
            else:
                self.conn.execute(
                    "UPDATE papers SET note=?,updated_at=? WHERE id=?",
                    (note, now_iso(), identifier),
                )
        elif table == "sessions":
            self.conn.execute("UPDATE sessions SET note=? WHERE id=?", (note, identifier))
        elif table == "experiments":
            self.conn.execute("UPDATE experiments SET note=? WHERE key=?", (note, identifier))
        else:
            raise ValueError("不支持的记录类型。")
        self.conn.commit()

    def update_digest_note(self, day: str, note: str) -> dict[str, Any]:
        self.get_digest(day)
        self.conn.execute(
            "UPDATE daily_digests SET manual_note=? WHERE day=?", (note, day)
        )
        self.conn.commit()
        return self.get_digest(day)
