from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "research_workbench" / "static"


def asset(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.current_page_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if dict(attrs).get("aria-current") == "page":
            self.current_page_count += 1

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.text.append(stripped)


def parsed_interface() -> VisibleTextParser:
    parser = VisibleTextParser()
    parser.feed(asset("index.html"))
    return parser


def test_interface_uses_direct_chinese_copy():
    visible_text = " ".join(parsed_interface().text)
    dynamic_copy = asset("app.js")
    combined = visible_text + dynamic_copy

    for required in (
        "每日简报",
        "项目统计",
        "最近对话",
        "最近实验",
        "研究文档",
        "添加文献",
    ):
        assert required in combined

    for removed in (
        "今天，我们把线索收回来。",
        "Daily synthesis",
        "Workspace pulse",
        "Recent threads",
        "Living documents",
        "一篇论文，只留一个身份。",
    ):
        assert removed not in combined


def test_navigation_exposes_current_page_semantics():
    parser = parsed_interface()
    script = asset("app.js")

    assert parser.current_page_count == 1
    assert 'setAttribute("aria-current", "page")' in script
    assert 'removeAttribute("aria-current")' in script


def test_editorial_design_tokens_and_accessibility_contracts():
    css = asset("styles.css")
    for token in (
        "--paper:",
        "--paper-raised:",
        "--ink:",
        "--muted:",
        "--line:",
        "--accent:",
        "--accent-soft:",
        "--success:",
    ):
        assert token in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert "linear-gradient" not in css
    assert "backdrop-filter" not in css


def test_responsive_layout_has_three_approved_ranges():
    css = asset("styles.css")
    assert "@media (max-width: 1199px)" in css
    assert "@media (max-width: 767px)" in css
    assert "min-height: 44px" in css
    assert "overflow-x: hidden" in css


def test_experiment_cards_wrap_long_research_identifiers():
    css = asset("styles.css")
    rule = re.search(r"\.experiment-card\s*\{([^}]*)\}", css, re.DOTALL)

    assert rule is not None
    assert "overflow-wrap: anywhere" in rule.group(1)


def test_paper_dialog_styles_match_the_form_id():
    css = asset("styles.css")

    assert "#paper-form {" in css
    assert "#paper-form label {" in css


def test_literature_library_loads_all_records_and_fetches_details_on_demand():
    html = asset("index.html")
    script = asset("app.js")

    assert 'id="paper-count"' in html
    assert 'await api(`/api/papers/${id}`)' in script
    assert '篇已调研文献' in script
    assert "function paperDocumentUrls" in script
    assert "阅读本地 PDF" in script
    assert "打开来源页" in script
    assert "在工作台内阅读" in script
    assert 'id="load-remote-pdf"' in script
    assert 'target="_blank" rel="noopener noreferrer"' in script


def test_experiment_records_offer_expandable_structured_details():
    script = asset("app.js")
    css = asset("styles.css")

    assert '<details class="experiment-details">' in script
    assert "研究问题" in script
    assert "实验方法" in script
    assert "结果与结论" in script
    assert ".experiment-details[open]" in css
    assert ".experiment-card:has(.experiment-details[open])" in css


def test_conversations_show_structured_research_briefs_and_keyword_chips():
    script = asset("app.js")
    css = asset("styles.css")
    html = asset("index.html")

    assert 'class="session-insight"' in script
    assert "结论摘要" in script
    assert "function conclusionPreview" in script
    assert "证据与路径" in script
    assert "下一步" in script
    assert "summary.result" in script
    assert "keywordChips(item.keywords" in script
    assert 'id="digest-results"' in html
    assert 'id="digest-experiments"' in html
    assert 'id="digest-research"' in html
    assert ".keyword-chip" in css
    assert ".session-insight" in css
    assert ".briefing-hero" in css


def test_daily_brief_supports_historical_day_navigation():
    html = asset("index.html")
    script = asset("app.js")

    assert 'id="previous-day"' in html
    assert 'id="next-day"' in html
    assert "shiftDashboardDay(-1)" in script
    assert "shiftDashboardDay(1)" in script
    assert "?day=" in script


def test_daily_tldr_has_a_clear_label_and_readable_type_hierarchy():
    html = asset("index.html")
    css = asset("styles.css")

    assert '<div class="insight-label"><span></span>TL;DR</div>' in html
    assert "font: 680 clamp(34px, 3.7vw, 48px)/1.12" in css
    assert "font: 720 clamp(20px, 1.6vw, 23px)/1.2" in css
    assert "font: 460 clamp(15px, 1.05vw, 16px)/1.72" in css
    assert ".digest-lead.markdown-body li" in css


def test_section_and_card_titles_are_larger_than_their_body_copy():
    css = asset("styles.css")

    for token in (
        "--type-body: 14px;",
        "--type-card-title: 16px;",
        "--type-section-title: 21px;",
        "font-size: var(--type-section-title);",
        "font-size: var(--type-card-title);",
        "font-size: 17px;",
    ):
        assert token in css

    assert css.index("--type-body: 14px;") < css.index("--type-card-title: 16px;")
    assert css.index("--type-card-title: 16px;") < css.index("--type-section-title: 21px;")


def test_markdown_and_latex_are_rendered_locally_and_safely():
    html = asset("index.html")
    script = asset("app.js")

    for resource in (
        "/static/vendor/marked/marked.umd.js",
        "/static/vendor/dompurify/purify.min.js",
        "/static/vendor/katex/katex.min.css",
        "/static/vendor/katex/katex.min.js",
        "/static/vendor/katex/auto-render.min.js",
    ):
        assert resource in html

    assert "DOMPurify.sanitize" in script
    assert "marked.parse" in script
    assert "renderMathInElement" in script
    assert 'output: "htmlAndMathml"' in script
    assert "trust: false" in script
    assert 'left: "\\\\[", right: "\\\\]"' in script
    assert 'left: "\\\\(", right: "\\\\)"' in script
    assert "looksLikeInlineMath" in script
    assert 'ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"]' in script
    assert "markdownHtml(message.content)" in script
    assert "section.markdown || section.body" in script
    assert "markdownPreviewHtml(conclusionPreview(item.summary?.result || item.tldr || item.preview))" in script
    assert 'for (const marker of ["**", "__", "~~", "`"])' in script
    assert 'renderRichText($("#recent-sessions"))' in script


def test_research_typography_handles_dense_text_code_tables_and_equations():
    styles = asset("styles.css")

    for token in (
        '--display:',
        '--mono:',
        'font-kerning: normal;',
        'text-autospace: normal;',
        'line-break: strict;',
        '.markdown-body pre {',
        '.markdown-body table {',
        '.katex-display {',
        'scrollbar-width: thin;',
    ):
        assert token in styles


def test_element_inspired_theme_uses_one_warm_component_palette():
    styles = asset("styles.css")

    for token in (
        "--paper: #f7f4ef;",
        "--paper-raised: #fffdf9;",
        "--ink: #352f2a;",
        "--accent: #ad5034;",
        "--accent-soft: #f9e9e1;",
        "/* Element-style component hierarchy */",
        ".segmented button.active",
        ".provider.claude",
        ".experiment-key",
    ):
        assert token in styles
    assert "#5b5ce2" not in styles
    assert "rgba(91, 92, 226" not in styles


def test_primary_warm_palette_keeps_text_contrast_accessible():
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast(foreground: str, background: str) -> float:
        first, second = luminance(foreground), luminance(background)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)

    for foreground, background in (
        ("#352f2a", "#f7f4ef"),
        ("#6f655d", "#f7f4ef"),
        ("#776d64", "#fffdf9"),
        ("#ffffff", "#ad5034"),
        ("#ad5034", "#f7f4ef"),
    ):
        assert contrast(foreground, background) >= 4.5


def test_vendored_markdown_and_math_assets_exist():
    vendor = STATIC / "vendor"
    for relative in (
        "marked/marked.umd.js",
        "dompurify/purify.min.js",
        "katex/katex.min.css",
        "katex/katex.min.js",
        "katex/auto-render.min.js",
    ):
        path = vendor / relative
        assert path.is_file()
        assert path.stat().st_size > 500


def test_rich_experiment_sections_can_shrink_on_mobile():
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert ".experiment-detail-section," in styles
    assert "min-width: 0;" in styles
    assert ".markdown-body table" in styles
    assert "overflow-x: auto;" in styles
