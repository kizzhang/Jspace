const state = {
  view: "today",
  dashboard: null,
  sessions: [], experiments: [], papers: [],
  provider: "", experimentStatus: "", query: "",
  activeSession: null, activePaper: null, activeDay: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value = "") => String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const compact = value => Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
const dateText = value => value ? new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "未知时间";
const statusClass = status => ["inbox","reading","read"].includes(status) ? status : "inbox";
const keywordChips = (keywords = [], limit = 8) => keywords.length ? `<div class="keyword-list">${keywords.slice(0, limit).map(keyword => `<span class="keyword-chip">${esc(keyword)}</span>`).join("")}</div>` : "";

function protectMath(source) {
  const segments = [];
  const stash = segment => {
    const token = `JSPACEMATH${segments.length}TOKEN`;
    segments.push(segment);
    return token;
  };
  let protectedSource = String(source || "");
  for (const pattern of [
    /\$\$[\s\S]+?\$\$/g,
    /\\\[[\s\S]+?\\\]/g,
    /\\\([\s\S]+?\\\)/g,
  ]) {
    protectedSource = protectedSource.replace(pattern, stash);
  }
  protectedSource = protectedSource.replace(
    /\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}[\s\S]+?\\end\{\1\}/g,
    segment => stash(`\\[${segment}\\]`),
  );
  protectedSource = protectedSource.replace(/\$(?!\$|\s)([^$\n]+?)(?<!\s)\$/g, (segment, expression) => {
    const value = expression.trim();
    const compactSymbol = /^[A-Za-z0-9]$/.test(value);
    const simpleEquation = /^[A-Za-z](?:\s*[=+*/^<>-]\s*[A-Za-z0-9])+$/i.test(value);
    const explicitMath = /\\[A-Za-z]+|[_^{}]|\d\s*[=+*/^<>-]|[=+*/^<>-]\s*\d/.test(value);
    const looksLikeInlineMath = value.length <= 180 && !/[`"']/.test(value) && (compactSymbol || simpleEquation || explicitMath);
    return looksLikeInlineMath ? stash(`\\(${value}\\)`) : segment;
  });
  return { protectedSource, segments };
}

function markdownHtml(value, inline = false) {
  if (!window.marked?.parse || !window.DOMPurify?.sanitize) {
    return esc(value).replace(/\n/g, "<br>");
  }
  const { protectedSource, segments } = protectMath(value);
  const rendered = inline
    ? marked.parseInline(protectedSource, { gfm: true, breaks: true })
    : marked.parse(protectedSource, { gfm: true, breaks: true });
  const clean = DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "option"],
  });
  return clean.replace(/JSPACEMATH(\d+)TOKEN/g, (_, index) => esc(segments[Number(index)] || ""));
}

function markdownInlineHtml(value) {
  const source = String(value || "").replace(/(^|\s)#{1,6}\s+/g, "$1");
  return markdownHtml(source, true).replace(/\*\*|__|~~/g, "");
}

function markdownPreviewHtml(value) {
  let source = String(value || "");
  for (const marker of ["**", "__", "~~", "`"]) {
    const count = source.split(marker).length - 1;
    if (count % 2) {
      const index = source.lastIndexOf(marker);
      source = `${source.slice(0, index)}${source.slice(index + marker.length)}`;
    }
  }
  return markdownInlineHtml(source);
}

function conclusionPreview(value) {
  const source = String(value || "");
  const judgment = source.match(/(?:^|\n)\s*-\s*\*\*判断\*\*[：:]\s*([^\n]+)/);
  return judgment ? judgment[1].trim() : source;
}

function safePaperUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

function paperDocumentUrls(item) {
  const sourceUrl = safePaperUrl(item.source_url)
    || (item.doi ? `https://doi.org/${encodeURI(item.doi)}` : "")
    || (item.arxiv_id ? `https://arxiv.org/abs/${encodeURIComponent(item.arxiv_id)}` : "");
  let onlinePdfUrl = "";
  if (item.arxiv_id) {
    onlinePdfUrl = `https://arxiv.org/pdf/${encodeURIComponent(item.arxiv_id)}`;
  } else if (/\.pdf(?:$|[?#])/i.test(sourceUrl)) {
    onlinePdfUrl = sourceUrl;
  } else {
    try {
      const parsed = new URL(sourceUrl);
      if (parsed.hostname === "openreview.net" && parsed.searchParams.get("id")) {
        onlinePdfUrl = `https://openreview.net/pdf?id=${encodeURIComponent(parsed.searchParams.get("id"))}`;
      } else if (parsed.hostname.endsWith("aclanthology.org")) {
        onlinePdfUrl = `${parsed.origin}${parsed.pathname.replace(/\/$/, "")}.pdf`;
      } else if (parsed.hostname === "proceedings.mlr.press" && parsed.pathname.endsWith(".html")) {
        onlinePdfUrl = `${parsed.origin}${parsed.pathname.replace(/\.html$/, ".pdf")}`;
      }
    } catch (_) { /* Source page remains available even when no PDF can be derived. */ }
  }
  return {
    localPdfUrl: item.pdf_path ? `/api/pdf/${encodeURIComponent(item.id)}` : "",
    onlinePdfUrl: safePaperUrl(onlinePdfUrl),
    sourceUrl,
  };
}

function paperReaderActions(item, urls) {
  const pdfUrl = urls.localPdfUrl || urls.onlinePdfUrl;
  const pdfLabel = urls.localPdfUrl ? "阅读本地 PDF" : "阅读 PDF";
  const links = [];
  if (pdfUrl) {
    links.push(`<a class="primary-button paper-link" href="${esc(pdfUrl)}" target="_blank" rel="noopener noreferrer">${pdfLabel}<span aria-hidden="true">↗</span></a>`);
  }
  if (urls.sourceUrl && urls.sourceUrl !== urls.onlinePdfUrl) {
    links.push(`<a class="quiet-button paper-link" href="${esc(urls.sourceUrl)}" target="_blank" rel="noopener noreferrer">打开来源页<span aria-hidden="true">↗</span></a>`);
  }
  return links.join("");
}

function renderRichText(root = document) {
  if (typeof window.renderMathInElement !== "function") return;
  const nodes = root.matches?.(".rich-text,.rich-inline")
    ? [root]
    : $$(".rich-text,.rich-inline", root);
  nodes.forEach(node => {
    if (node.dataset.mathRendered === "true") return;
    renderMathInElement(node, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
      ],
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      output: "htmlAndMathml",
      trust: false,
      throwOnError: false,
      strict: "ignore",
      macros: {
        "\\RR": "\\mathbb{R}",
        "\\EE": "\\mathbb{E}",
        "\\PP": "\\mathbb{P}",
        "\\KL": "\\operatorname{KL}",
      },
    });
    node.dataset.mathRendered = "true";
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove("show"), 2400);
}

function setView(view) {
  state.view = view;
  $$(".nav-item").forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${view}`));
  const headings = {
    today: ["JSpace", "每日简报"],
    conversations: ["JSpace", "研究对话"],
    experiments: ["JSpace", "实验记录"],
    literature: ["JSpace", "文献资料"],
  };
  $("#view-eyebrow").textContent = headings[view][0]; $("#view-title").textContent = headings[view][1];
  if (view === "conversations") loadSessions();
  if (view === "experiments") loadExperiments();
  if (view === "literature") loadPapers();
}

async function loadDashboard() {
  const dayQuery = state.activeDay ? `?day=${encodeURIComponent(state.activeDay)}` : "";
  const data = await api(`/api/dashboard${dayQuery}`); state.dashboard = data; state.activeDay = data.day;
  $("#today-date").textContent = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "short" }).format(new Date(`${data.day}T12:00:00`));
  const localToday = new Date();
  const todayKey = `${localToday.getFullYear()}-${String(localToday.getMonth() + 1).padStart(2, "0")}-${String(localToday.getDate()).padStart(2, "0")}`;
  $("#next-day").disabled = data.day >= todayKey;
  $("#digest-body").innerHTML = markdownHtml(data.digest.tldr || "今天尚未形成明确结论。");
  $("#digest-body").classList.add("rich-text", "markdown-body");
  $("#digest-keywords").innerHTML = keywordChips(data.digest.keywords || [], 12);
  renderDigestSections(data.digest.sections || {});
  renderRichText($("#digest-body"));
  $("#digest-note").value = data.digest.manual_note || "";
  $("#stat-experiments").textContent = compact(data.counts.experiments);
  $("#stat-sessions").textContent = compact(data.counts.sessions);
  $("#stat-papers").textContent = compact(data.counts.papers);
  $("#pulse-note").textContent = data.counts.notes_needed ? `${data.counts.notes_needed} 段对话待补充备注。` : "所有对话均有备注。";
  $("#sync-label").textContent = data.last_sync ? `上次同步 ${dateText(data.last_sync)}` : "尚未同步";
  $("#sync-label-secondary").textContent = data.last_sync ? dateText(data.last_sync) : "尚未同步";
  renderRecentSessions(data.recent_sessions); renderRecentExperiments(data.recent_experiments); renderDocs(data.key_docs);
}

function shiftDashboardDay(offset) {
  const day = state.activeDay || state.dashboard?.day;
  if (!day) return;
  const current = new Date(`${day}T12:00:00`);
  current.setDate(current.getDate() + offset);
  state.activeDay = `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, "0")}-${String(current.getDate()).padStart(2, "0")}`;
  loadDashboard().catch(error => toast(error.message));
}

function bindSessionLinks(root) {
  $$("[data-session]", root).forEach(node => {
    const activate = () => {
      setView("conversations");
      setTimeout(() => openSession(decodeURIComponent(node.dataset.session)), 0);
    };
    node.tabIndex = 0;
    node.setAttribute("role", "link");
    node.addEventListener("click", activate);
    node.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    });
  });
}

function renderDigestSections(sections) {
  const results = sections.results || [], experiments = sections.experiments || [], research = sections.research || [];
  $("#digest-results").innerHTML = results.length ? results.slice(0, 5).map(item => `
    <article class="brief-item result-item" ${item.session_id ? `data-session="${encodeURIComponent(item.session_id)}"` : ""}>
      <div class="brief-item-meta"><span class="provider ${item.provider}">${item.provider}</span>${(item.experiment_ids || []).map(id => `<span class="experiment-key">${esc(id)}</span>`).join("")}</div>
      <h4 class="rich-inline">${markdownInlineHtml(item.title)}</h4>
      <div class="brief-result rich-text">${markdownHtml(item.result)}</div>
      ${item.next_step && item.next_step !== "未明确记录下一步。" ? `<div class="next-step"><span>下一步</span><p class="rich-inline">${markdownInlineHtml(item.next_step)}</p></div>` : ""}
    </article>`).join("") : `<div class="brief-empty">今天尚未形成明确结果</div>`;
  $("#digest-experiments").innerHTML = experiments.length ? experiments.slice(0, 5).map(item => `
    <article class="brief-item experiment-brief-item">
      <div class="brief-item-meta"><span class="experiment-key">${esc(item.key)}</span><span class="status">${esc(item.status)}</span></div>
      <h4 class="rich-inline">${markdownInlineHtml(item.title)}</h4>
      <p class="rich-inline">${markdownPreviewHtml(item.result)}</p>
    </article>`).join("") : `<div class="brief-empty">今天没有实验变动</div>`;
  $("#digest-research").innerHTML = research.length ? research.slice(0, 6).map(item => `
    <article class="brief-item research-item" data-session="${encodeURIComponent(item.session_id)}">
      <div class="brief-item-meta"><span class="provider ${item.provider}">${item.provider}</span></div>
      <h4 class="rich-inline">${markdownInlineHtml(item.title)}</h4>
      <p class="research-question rich-inline">${markdownPreviewHtml(item.objective)}</p>
      ${item.approach && !item.approach.startsWith("对话中未") ? `<p class="research-approach rich-inline"><span>路径</span>${markdownPreviewHtml(item.approach)}</p>` : ""}
      ${keywordChips(item.keywords || [], 5)}
    </article>`).join("") : `<div class="brief-empty">今天没有独立调研记录</div>`;
  renderRichText($("#digest-results")); renderRichText($("#digest-experiments")); renderRichText($("#digest-research"));
  bindSessionLinks($("#digest-results")); bindSessionLinks($("#digest-research"));
}

function renderRecentSessions(items) {
  $("#recent-sessions").innerHTML = items.length ? items.map(item => `
    <div class="activity-row" data-session="${encodeURIComponent(item.id)}">
      <span class="time">${dateText(item.ended_at)}</span><span class="provider ${item.provider}">${item.provider === "claude" ? "Claude" : "Codex"}</span>
      <span class="activity-title rich-inline">${markdownInlineHtml(item.title)}</span><span class="activity-preview rich-inline">${markdownPreviewHtml(conclusionPreview(item.summary?.result || item.tldr || item.preview))}</span>
    </div>`).join("") : `<div class="empty-state"><p>暂无当前项目的 AI 对话。</p></div>`;
  renderRichText($("#recent-sessions"));
  bindSessionLinks($("#recent-sessions"));
}

function renderRecentExperiments(items) {
  $("#recent-experiments").innerHTML = items.map(item => `<div class="stack-item"><span class="experiment-key">${esc(item.key)}</span><div><strong class="rich-inline">${markdownInlineHtml(item.title)}</strong><p>${dateText(item.updated_at)}</p></div><span class="status">${esc(item.status_label)}</span></div>`).join("");
  renderRichText($("#recent-experiments"));
}
function renderDocs(items) {
  $("#key-docs").innerHTML = items.map(item => `<div class="document-item"><strong>${esc(item.name.replace(/_/g," "))}</strong><p>${esc(item.path)} · ${dateText(item.updated_at)}</p></div>`).join("");
}

async function loadSessions() {
  const params = new URLSearchParams(); if (state.query) params.set("q", state.query); if (state.provider) params.set("provider", state.provider);
  state.sessions = await api(`/api/sessions?${params}`); $("#session-count").textContent = `${state.sessions.length} 段对话`;
  const list = $("#session-list");
  list.innerHTML = state.sessions.length ? state.sessions.map(item => `<article class="record ${state.activeSession === item.id ? "active" : ""}" data-id="${encodeURIComponent(item.id)}"><div class="record-top"><span class="provider ${item.provider}">${item.provider}</span><span class="time">${dateText(item.ended_at)}</span></div><h3 class="rich-inline">${markdownInlineHtml(item.title)}</h3><p class="record-result rich-inline">${markdownPreviewHtml(conclusionPreview(item.summary?.result || item.tldr || item.preview))}</p>${keywordChips(item.keywords, 4)}</article>`).join("") : `<div class="empty-state"><h3>没有匹配对话</h3><p>试试更短的关键词。</p></div>`;
  renderRichText(list);
  $$(".record", list).forEach(node => {
    const activate = () => openSession(decodeURIComponent(node.dataset.id));
    node.tabIndex = 0; node.setAttribute("role", "button"); node.addEventListener("click", activate);
    node.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); } });
  });
}

async function openSession(id) {
  state.activeSession = id; const item = await api(`/api/sessions/${encodeURIComponent(id)}`); await loadSessions();
  const summary = item.summary || {};
  $("#session-detail").innerHTML = `<header class="detail-heading"><div class="detail-meta"><span class="provider ${item.provider}">${item.provider}</span><span>${dateText(item.ended_at)}</span><span>${item.message_count} 条消息</span></div><h2 class="rich-inline">${markdownInlineHtml(item.title)}</h2>${keywordChips(item.keywords)}</header><section class="session-insight"><div class="summary-label"><span></span>结论摘要</div><div class="session-result rich-text markdown-body">${markdownHtml(summary.result || item.tldr || item.preview)}</div></section><div class="summary-grid"><article><span class="summary-field-label">研究问题</span><div class="rich-text markdown-body">${markdownHtml(summary.objective || "未单独提炼研究问题。")}</div></article><article><span class="summary-field-label">证据与路径</span><div class="rich-text markdown-body">${markdownHtml(summary.approach || "未单独沉淀证据摘要。")}</div></article><article><span class="summary-field-label">下一步</span><div class="rich-text markdown-body">${markdownHtml(summary.next_step || "未明确记录下一步。")}</div></article></div><details class="transcript-panel"><summary><span>完整对话</span><small>${item.message_count} 条消息</small></summary><div class="messages">${item.messages.map(message => `<article class="message ${message.role}"><span class="role">${message.role === "user" ? "你" : item.provider}</span><div class="rich-text markdown-body">${markdownHtml(message.content)}</div></article>`).join("")}</div></details><div class="detail-note"><label class="note-field"><span>研究备注</span><textarea rows="4" id="session-note" placeholder="这段对话改变了什么判断？">${esc(item.note)}</textarea></label><button class="text-button" id="save-session-note">保存备注</button></div>`;
  renderRichText($("#session-detail"));
  $("#save-session-note").addEventListener("click", async () => { await api(`/api/sessions/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ note: $("#session-note").value }) }); toast("对话备注已保存"); });
}

function renderExperimentDetails(item) {
  const details = item.metadata?.details || {};
  const labels = ["研究问题", "实验方法", "结果与结论"];
  const sections = labels.map(label => (details.sections || []).find(section => section.label === label)).filter(Boolean);
  const sectionHtml = sections.length ? sections.map(section => `<section class="experiment-detail-section"><h4>${esc(section.label)}</h4><div class="rich-text markdown-body">${markdownHtml(section.markdown || section.body)}</div>${section.source ? `<small>来源：${esc(section.source)}</small>` : ""}</section>`).join("") : `<section class="experiment-detail-section"><h4>实验说明</h4><div class="rich-text markdown-body">${markdownHtml(item.summary || "暂无结构化说明。")}</div></section>`;
  const artifactHtml = (details.artifacts || []).length ? `<section class="experiment-artifacts"><h4>相关材料</h4>${details.artifacts.map(group => `<div class="artifact-group"><strong>${esc(group.label)} <span>${group.count}</span></strong><ul>${group.paths.map(path => `<li>${esc(path)}</li>`).join("")}</ul></div>`).join("")}</section>` : "";
  return `<details class="experiment-details"><summary><span class="details-action"></span><span class="details-hint">问题、方法、结论与文件</span></summary><div class="experiment-detail-body">${sectionHtml}${artifactHtml}<section class="experiment-note"><label for="note-${esc(item.key)}">实验备注</label><textarea id="note-${esc(item.key)}" data-experiment-note="${esc(item.key)}" rows="3" placeholder="补充结论、异常或下一步…">${esc(item.note)}</textarea></section></div></details>`;
}

async function loadExperiments() {
  const params = new URLSearchParams(); if (state.query) params.set("q", state.query); if (state.experimentStatus) params.set("status", state.experimentStatus);
  state.experiments = await api(`/api/experiments?${params}`); $("#experiment-count").textContent = `${state.experiments.length} 个实验`;
  $("#experiment-list").innerHTML = state.experiments.length ? state.experiments.map(item => `<article class="experiment-card"><div class="record-top"><span class="experiment-key">${esc(item.key)}</span><span class="status">${esc(item.status_label)}</span></div><h3 class="rich-inline">${markdownInlineHtml(item.title)}</h3><div class="experiment-overview"><strong>实验内容</strong><div class="rich-text markdown-body">${markdownHtml(item.metadata?.details?.overview_markdown || item.metadata?.details?.overview || item.summary)}</div></div><div class="experiment-counts"><span>脚本 ${item.source_count}</span><span>结果 ${item.result_count}</span><span>记录 ${item.doc_count}</span><span>更新 ${dateText(item.updated_at)}</span></div>${renderExperimentDetails(item)}</article>`).join("") : `<div class="empty-state"><h3>没有匹配实验</h3></div>`;
  renderRichText($("#experiment-list"));
  $$('[data-experiment-note]').forEach(node => node.addEventListener("change", async () => { await api(`/api/experiments/${encodeURIComponent(node.dataset.experimentNote)}`, { method: "PATCH", body: JSON.stringify({ note: node.value }) }); toast(`${node.dataset.experimentNote} 备注已保存`); }));
}

async function loadPapers() {
  const params = new URLSearchParams(); if (state.query) params.set("q", state.query);
  state.papers = await api(`/api/papers?${params}`);
  $("#paper-count").textContent = `${state.papers.length} 篇已调研文献`;
  $("#paper-list").innerHTML = state.papers.length ? state.papers.map(item => `<article class="paper-row ${state.activePaper === item.id ? "active" : ""}" data-paper="${item.id}"><div class="record-top"><span class="paper-id">${esc(item.doi || (item.arxiv_id ? `arXiv:${item.arxiv_id}` : "本地 PDF"))}</span><i class="dot ${statusClass(item.status)}"></i></div><h3 class="rich-inline">${markdownInlineHtml(item.title)}</h3><p>${esc(item.authors || "作者信息待补充")}${item.year ? ` · ${item.year}` : ""}</p></article>`).join("") : `<div class="empty-state"><span aria-hidden="true">▤</span><h3>暂无文献</h3><p>点击右上角“添加文献”。</p></div>`;
  renderRichText($("#paper-list"));
  $$('[data-paper]').forEach(node => {
    const activate = () => openPaper(Number(node.dataset.paper));
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.addEventListener("click", activate);
    node.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    });
  });
  if (state.papers.length) {
    const selected = state.papers.find(item => item.id === state.activePaper) || state.papers[0];
    await openPaper(selected.id);
  } else {
    state.activePaper = null;
  }
}

async function openPaper(id) {
  state.activePaper = id;
  $$('[data-paper]').forEach(node => node.classList.toggle("active", Number(node.dataset.paper) === id));
  const item = await api(`/api/papers/${id}`);
  const abstract = item.abstract || "暂无摘要。可通过 DOI 或 arXiv 更新。";
  const urls = paperDocumentUrls(item);
  const readerActions = paperReaderActions(item, urls);
  const reader = urls.localPdfUrl
    ? `<iframe class="pdf-frame" title="${esc(item.title)} PDF 预览" src="${esc(urls.localPdfUrl)}#view=FitH"></iframe>`
    : urls.onlinePdfUrl
      ? `<section class="remote-reader"><div><span class="summary-field-label">在线全文</span><h3>在工作台内阅读 PDF</h3><p>按需加载在线 PDF；如果站点限制嵌入，可使用上方“阅读 PDF”在新标签页打开。</p></div><button class="quiet-button" id="load-remote-pdf" type="button">在工作台内阅读</button><div id="remote-pdf-slot"></div></section>`
      : `<div class="no-pdf"><div><strong>暂无可直接预览的 PDF</strong><p>可以通过上方来源页阅读全文或查找出版版本。</p></div></div>`;
  $("#paper-detail").innerHTML = `<header class="detail-heading"><div class="detail-meta"><span class="paper-id">${esc(item.doi || item.arxiv_id || "本地文献")}</span><span>${item.metadata_updated_at ? `元数据 ${dateText(item.metadata_updated_at)}` : "元数据待更新"}</span></div><h2 class="rich-inline">${markdownInlineHtml(item.title)}</h2><div class="paper-reader-actions">${readerActions}</div></header><section class="paper-summary"><span class="summary-field-label">摘要</span><div class="rich-text markdown-body">${markdownHtml(abstract)}</div><label class="note-field"><span>简短备注</span><textarea id="paper-detail-note" rows="3" placeholder="记录贡献、可信度或与实验的关系">${esc(item.note)}</textarea></label><div class="paper-actions"><select id="paper-status"><option value="inbox">待阅读</option><option value="reading">阅读中</option><option value="read">已读</option><option value="cited">已引用</option></select><button class="quiet-button" id="save-paper">保存</button>${(item.doi || item.arxiv_id) ? `<button class="text-button" id="refresh-paper">更新元数据 ↻</button>` : ""}</div></section>${reader}`;
  renderRichText($("#paper-detail"));
  $("#paper-status").value = item.status;
  $("#save-paper").addEventListener("click", async () => { await api(`/api/papers/${id}`, { method: "PATCH", body: JSON.stringify({ note: $("#paper-detail-note").value, status: $("#paper-status").value }) }); toast("文献状态与备注已保存"); await loadPapers(); });
  if ($("#refresh-paper")) $("#refresh-paper").addEventListener("click", async () => { $("#refresh-paper").textContent = "更新中…"; try { await api(`/api/papers/${id}/refresh`, { method: "POST", body: "{}" }); toast("文献元数据已更新"); await loadPapers(); } catch (error) { toast(error.message); } });
  if ($("#load-remote-pdf")) $("#load-remote-pdf").addEventListener("click", () => {
    $("#remote-pdf-slot").innerHTML = `<iframe class="pdf-frame" title="${esc(item.title)} 在线 PDF" src="${esc(urls.onlinePdfUrl)}#view=FitH"></iframe>`;
    $("#load-remote-pdf").remove();
  });
}

async function syncNow() {
  const button = $("#sync-button"), stateNode = $(".sync-state"); button.disabled = true; button.textContent = "同步中…"; stateNode.classList.add("busy");
  try { const result = await api("/api/sync", { method: "POST", body: "{}" }); toast(`已同步 ${result.conversations_updated} 段对话`); await loadDashboard(); if (state.view === "conversations") await loadSessions(); if (state.view === "experiments") await loadExperiments(); if (state.view === "literature") await loadPapers(); }
  catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = "同步记录"; stateNode.classList.remove("busy"); }
}

function openPaperDialog() { $("#paper-form-error").textContent = ""; $("#paper-dialog").showModal(); }
function closePaperDialog() { $("#paper-dialog").close(); }
async function submitPaper(event) {
  event.preventDefault(); const identity = $("#paper-identity").value.trim(); const path = $("#paper-path").value.trim(); const note = $("#paper-note").value.trim();
  const payload = { pdf_path: path, note, refresh: true };
  if (/10\.\d{4,9}\//i.test(identity)) payload.doi = identity;
  else if (/arxiv|\d{4}\.\d{4,5}/i.test(identity)) payload.arxiv_id = identity;
  else payload.title = identity;
  if (!identity && !path) { $("#paper-form-error").textContent = "请至少填写文献身份或本地 PDF 路径。"; return; }
  try { const result = await api("/api/papers", { method: "POST", body: JSON.stringify(payload) }); closePaperDialog(); event.target.reset(); toast("文献已添加"); state.activePaper = result.paper.id; setView("literature"); await loadPapers(); }
  catch (error) { $("#paper-form-error").textContent = error.message; }
}

document.addEventListener("DOMContentLoaded", async () => {
  $$(".nav-item,.jump").forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#sync-button").addEventListener("click", syncNow);
  $("#previous-day").addEventListener("click", () => shiftDashboardDay(-1));
  $("#next-day").addEventListener("click", () => shiftDashboardDay(1));
  $("#save-digest").addEventListener("click", async () => { await api(`/api/digests/${state.dashboard.day}`, { method: "PATCH", body: JSON.stringify({ manual_note: $("#digest-note").value }) }); $("#digest-save-state").textContent = "已保存"; toast("备注已保存"); });
  $("#global-search").addEventListener("keydown", event => { if (event.key === "Enter") { state.query = event.target.value.trim(); if (state.view === "today") setView("conversations"); else setView(state.view); } });
  $$("#provider-filter button").forEach(button => button.addEventListener("click", () => { $$("#provider-filter button").forEach(item => item.classList.remove("active")); button.classList.add("active"); state.provider = button.dataset.value; loadSessions(); }));
  $$("#experiment-filter button").forEach(button => button.addEventListener("click", () => { $$("#experiment-filter button").forEach(item => item.classList.remove("active")); button.classList.add("active"); state.experimentStatus = button.dataset.value; loadExperiments(); }));
  $("#add-paper-button").addEventListener("click", openPaperDialog); $("#close-paper-dialog").addEventListener("click", closePaperDialog); $("#cancel-paper-dialog").addEventListener("click", closePaperDialog); $("#paper-form").addEventListener("submit", submitPaper);
  try { await loadDashboard(); } catch (error) { toast(error.message); }
});
