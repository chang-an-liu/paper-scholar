#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_render_html.py

Render a polished side-by-side HTML paper reading report from extracted PDF text
and a Claude-written analysis.md.

UI v2 goals:
- Left pane shows the original PDF, not only extracted text.
- Right pane shows the detailed Chinese reading.
- Mathematical formulas written in LaTeX are rendered by MathJax.
- Important notes can be highlighted with [!KEY], [!FORMULA], [!WARN].
- Links like [[pdf:5|查看原文 Page 5]] jump the left PDF viewer to page 5.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
from pathlib import Path
from typing import Callable, List, Tuple
from urllib.parse import quote


DEFAULT_MATHJAX_SRC = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"


def _slugify(text: str, fallback: str = "section") -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip()).strip("-")
    return (slug or fallback)[:100]


def _pdf_uri(pdf_path: str) -> str:
    """Return a browser-friendly URI for a local or relative PDF path."""
    if not pdf_path:
        return ""
    raw = str(pdf_path).strip().strip('"')
    if not raw:
        return ""

    if re.match(r"^https?://", raw, flags=re.I) or raw.startswith("file://"):
        return raw

    # Windows absolute path: C:\foo\bar.pdf -> file:///C:/foo/bar.pdf
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        normalized = raw.replace("\\", "/")
        return "file:///" + quote(normalized, safe=":/")

    # UNC path: \\server\share\paper.pdf -> file:////server/share/paper.pdf
    if raw.startswith("\\\\"):
        normalized = raw.replace("\\", "/")
        return "file:" + quote(normalized, safe="/")

    try:
        p = Path(raw)
        if p.is_absolute():
            return p.as_uri()
    except Exception:
        pass

    # Keep relative path relative to the generated HTML file. Quote unsafe chars.
    return quote(raw.replace("\\", "/"), safe="/:._-()[]%")


def _stash_placeholders(text: str, rules: List[Tuple[re.Pattern, Callable[[re.Match], str]]]) -> Tuple[str, List[str]]:
    placeholders: List[str] = []

    def stash(raw_html: str) -> str:
        idx = len(placeholders)
        placeholders.append(raw_html)
        return f"@@HTML_PLACEHOLDER_{idx}@@"

    for pattern, repl in rules:
        text = pattern.sub(lambda m: stash(repl(m)), text)
    return text, placeholders


def _restore_placeholders(text: str, placeholders: List[str]) -> str:
    for idx, raw in enumerate(placeholders):
        text = text.replace(f"@@HTML_PLACEHOLDER_{idx}@@", raw)
    return text


def md_inline(s: str) -> str:
    """A small inline markdown renderer that preserves MathJax expressions."""

    pdf_link_pat = re.compile(r"\[\[pdf:(\d+)\|([^\]]+)\]\]")
    code_pat = re.compile(r"`([^`]+)`")
    paren_math_pat = re.compile(r"\\\((.+?)\\\)")
    bracket_math_pat = re.compile(r"\\\[(.+?)\\\]", flags=re.S)
    dollar_math_pat = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)")

    rules: List[Tuple[re.Pattern, Callable[[re.Match], str]]] = [
        (
            pdf_link_pat,
            lambda m: (
                f'<button type="button" class="pdf-jump" onclick="setPdfPage({int(m.group(1))})">'
                f'{html.escape(m.group(2))}</button>'
            ),
        ),
        (code_pat, lambda m: f"<code>{html.escape(m.group(1))}</code>"),
        (bracket_math_pat, lambda m: f'<span class="math-inline">\\[{html.escape(m.group(1))}\\]</span>'),
        (paren_math_pat, lambda m: f'<span class="math-inline">\\({html.escape(m.group(1))}\\)</span>'),
        (dollar_math_pat, lambda m: f'<span class="math-inline">\\({html.escape(m.group(1))}\\)</span>'),
    ]

    protected, placeholders = _stash_placeholders(s, rules)
    protected = html.escape(protected)
    protected = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", protected)
    protected = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", protected)
    return _restore_placeholders(protected, placeholders)


def _render_table(rows: List[str]) -> str:
    def split_row(row: str) -> List[str]:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [cell.strip() for cell in row.split("|")]

    if len(rows) < 2:
        return "\n".join(f"<p>{md_inline(r)}</p>" for r in rows)

    header = split_row(rows[0])
    body = rows[2:]
    thead = "".join(f"<th>{md_inline(c)}</th>" for c in header)
    trs = []
    for row in body:
        cells = split_row(row)
        trs.append("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in cells) + "</tr>")
    return "<div class=\"table-wrap\"><table><thead><tr>" + thead + "</tr></thead><tbody>" + "".join(trs) + "</tbody></table></div>"


def _is_table_start(lines: List[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    if "|" not in lines[i] or "|" not in lines[i + 1]:
        return False
    sep = lines[i + 1].strip()
    return bool(re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", sep))


def _render_callout(kind: str, body_lines: List[str]) -> str:
    kind = kind.lower()
    titles = {
        "key": "重点结论",
        "formula": "公式精讲",
        "warn": "潜在问题",
        "note": "阅读提示",
        "review": "审稿人视角",
        "idea": "Research Idea",
        "read": "阅读优先级",
    }
    icons = {
        "key": "◆",
        "formula": "∑",
        "warn": "!",
        "note": "i",
        "review": "R",
        "idea": "*",
        "read": "✓",
    }


    title = titles.get(kind, "阅读提示")
    icon = icons.get(kind, "i")
    body_html = "\n".join(f"<p>{md_inline(line.strip())}</p>" for line in body_lines if line.strip())
    return f'<div class="callout callout-{html.escape(kind)}"><div class="callout-title"><span>{icon}</span>{title}</div>{body_html}</div>'


def markdown_to_html(md: str) -> str:
    lines = md.splitlines()
    out: List[str] = []
    in_ul = False
    in_ol = False
    in_code = False
    code_buf: List[str] = []
    code_lang = ""
    i = 0

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if not in_code:
                close_lists()
                in_code = True
                code_lang = stripped[3:].strip()
                code_buf = []
            else:
                lang_class = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
                out.append("<pre><code" + lang_class + ">" + html.escape("\n".join(code_buf)) + "</code></pre>")
                in_code = False
                code_lang = ""
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Display math blocks: $$ ... $$ or \[ ... \]
        if stripped == "$$" or stripped == "\\[":
            close_lists()
            end = "$$" if stripped == "$$" else "\\]"
            math_lines: List[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != end:
                math_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            math = html.escape("\n".join(math_lines).strip())
            out.append(f'<div class="math-display">\\[{math}\\]</div>')
            continue

        # Single-line display math: $$ ... $$
        m_single_math = re.match(r"^\$\$\s*(.*?)\s*\$\$$", stripped)
        if m_single_math:
            close_lists()
            out.append(f'<div class="math-display">\\[{html.escape(m_single_math.group(1))}\\]</div>')
            i += 1
            continue

        # Callouts: > [!KEY] ...
        if stripped.startswith(">"):
            close_lists()
            call_lines: List[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                call_lines.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            if call_lines:
                first = call_lines[0].strip()
                m_call = re.match(r"^\[!(KEY|FORMULA|WARN|NOTE|REVIEW|IDEA|READ)\]\s*(.*)$", first, flags=re.I)
                if m_call:
                    kind = m_call.group(1).lower()
                    rest = m_call.group(2).strip()
                    body = ([rest] if rest else []) + call_lines[1:]
                    out.append(_render_callout(kind, body))
                else:
                    quote_html = "\n".join(f"<p>{md_inline(x)}</p>" for x in call_lines if x.strip())
                    out.append(f"<blockquote>{quote_html}</blockquote>")
            continue

        # Tables
        if _is_table_start(lines, i):
            close_lists()
            table_lines = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines):
                if not lines[i].strip():
                    if i+ 1 < len(lines) and "|" in lines[i+1]:
                        i += 1
                        continue
                    break
                if "|" not in lines[i]:
                    break
                table_lines.append(lines[i])
                i += 1
            out.append(_render_table(table_lines))
            continue

        if not stripped:
            close_lists()
            i += 1
            continue

        m_heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m_heading:
            close_lists()
            level = len(m_heading.group(1))
            text_raw = m_heading.group(2).strip()
            text = md_inline(text_raw)
            anchor = _slugify(text_raw, f"h{level}")
            out.append(f'<h{level} id="{html.escape(anchor)}">{text}</h{level}>')
            i += 1
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item = re.sub(r"^\s*[-*+]\s+", "", line).strip()
            out.append("<li>" + md_inline(item) + "</li>")
            i += 1
            continue

        if re.match(r"^\s*\d+[.)]\s+", line):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            item = re.sub(r"^\s*\d+[.)]\s+", "", line).strip()
            out.append("<li>" + md_inline(item) + "</li>")
            i += 1
            continue

        close_lists()
        out.append("<p>" + md_inline(stripped) + "</p>")
        i += 1

    close_lists()
    if in_code:
        lang_class = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
        out.append("<pre><code" + lang_class + ">" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "\n".join(out)


def section_cards(sections: list) -> str:
    cards = []
    for i, sec in enumerate(sections, start=1):
        title = html.escape(sec.get("title") or f"Section {i}")
        page = html.escape(str(sec.get("start_page", "?")))
        text = html.escape(sec.get("text") or "[No text extracted]")
        cards.append(f"""
        <article class="section-card" data-page="{page}">
          <div class="section-card-top">
            <h3>{i}. {title}</h3>
            <button type="button" class="mini-jump" onclick="setPdfPage('{page}')">Page {page}</button>
          </div>
          <pre>{text}</pre>
        </article>
        """)
    return "\n".join(cards)


def render(extracted: dict, analysis_md: str, mathjax_src: str = DEFAULT_MATHJAX_SRC) -> str:
    meta = extracted.get("metadata", {}) or {}
    pdf_path = extracted.get("pdf_path", "")
    pdf_src = _pdf_uri(pdf_path)
    title = meta.get("title") or Path(str(pdf_path)).stem or "Paper Reading"
    sections = extracted.get("sections") or []
    eqs = extracted.get("equation_candidates") or []
    generated_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    eq_html = "".join(
        f"<li><button type=\"button\" class=\"mini-jump\" onclick=\"setPdfPage({html.escape(str(e.get('page') or 1))})\">Page {html.escape(str(e.get('page')))}</button> "
        f"<span>line {html.escape(str(e.get('line')))}:</span> <code>{html.escape(e.get('text',''))}</code></li>"
        for e in eqs[:80]
    ) or "<li>No equation candidates detected.</li>"
    analysis_html = markdown_to_html(analysis_md)
    orig_cards = section_cards(sections)
    pdf_iframe_src = (pdf_src + ("#page=1" if pdf_src else ""))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Paper Reading - {html.escape(title)}</title>
<script>
window.MathJax = {{
  tex: {{
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    processEscapes: true,
    tags: 'ams'
  }},
  svg: {{ fontCache: 'global' }},
  options: {{ skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] }}
}};
</script>
<script defer src="{html.escape(mathjax_src)}"></script>
<style>
:root {{
  --bg0: #0f172a;
  --bg1: #eef2ff;
  --bg2: #f8fafc;
  --panel: rgba(255, 255, 255, 0.92);
  --panel-solid: #ffffff;
  --text: #172033;
  --muted: #667085;
  --border: rgba(148, 163, 184, 0.28);
  --code: #f3f6fb;
  --accent: #3454d1;
  --accent2: #7c3aed;
  --key: #1d4ed8;
  --formula: #047857;
  --warn: #b42318;
  --shadow: 0 18px 55px rgba(15, 23, 42, 0.12);
  --shadow-soft: 0 10px 28px rgba(15, 23, 42, 0.08);
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(124,58,237,.22), transparent 28rem),
    radial-gradient(circle at top right, rgba(37,99,235,.18), transparent 30rem),
    linear-gradient(180deg, #f8fbff 0%, #eef2ff 46%, #f8fafc 100%);
}}
.header {{
  position: sticky;
  top: 0;
  z-index: 30;
  color: white;
  background: linear-gradient(135deg, #0f172a 0%, #1e2a78 48%, #4932a8 100%);
  box-shadow: 0 12px 35px rgba(15, 23, 42, 0.22);
}}
.header-inner {{ padding: 22px 30px 20px; }}
.header h1 {{ margin: 0 0 10px; font-size: clamp(20px, 2.25vw, 30px); line-height: 1.22; letter-spacing: -0.02em; }}
.meta-row {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; color: rgba(255,255,255,.78); font-size: 13px; }}
.badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border: 1px solid rgba(255,255,255,.18); border-radius: 999px; background: rgba(255,255,255,.08); backdrop-filter: blur(8px); }}
.layout {{
  display: grid;
  grid-template-columns: minmax(420px, 0.92fr) minmax(520px, 1.08fr);
  gap: 18px;
  padding: 18px;
  align-items: start;
}}
.pane {{
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 22px;
  overflow: hidden;
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
}}
.pane-title {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  min-height: 58px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--border);
  font-weight: 800;
  background: rgba(255,255,255,.76);
  position: sticky;
  top: 85px;
  z-index: 12;
}}
.pane-title small {{ font-weight: 500; color: var(--muted); }}
.content {{ padding: 20px; }}
.pdf-pane {{ position: sticky; top: 104px; }}
.pdf-toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
.pdf-frame-wrap {{ height: calc(100vh - 185px); min-height: 620px; background: #111827; }}
.pdf-frame {{ width: 100%; height: 100%; border: 0; background: #111827; }}
.pdf-empty {{ padding: 28px; color: #334155; background: #fff; }}
a.button, button.pdf-jump, button.mini-jump, .toolbar-btn {{
  appearance: none;
  border: 1px solid rgba(52,84,209,.18);
  background: rgba(52,84,209,.08);
  color: #263ea8;
  border-radius: 999px;
  padding: 7px 11px;
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition: transform .15s ease, background .15s ease, border-color .15s ease;
}}
a.button:hover, button.pdf-jump:hover, button.mini-jump:hover, .toolbar-btn:hover {{ transform: translateY(-1px); background: rgba(52,84,209,.13); border-color: rgba(52,84,209,.34); }}
button.pdf-jump {{ margin: 0 2px; padding: 4px 9px; vertical-align: baseline; }}
button.mini-jump {{ padding: 4px 9px; font-size: 11px; white-space: nowrap; }}
.article {{ font-size: 15.5px; }}
.article h1 {{ margin: 4px 0 18px; font-size: 28px; letter-spacing: -0.03em; }}
.article h2 {{
  margin: 34px 0 14px;
  padding-top: 22px;
  border-top: 1px solid var(--border);
  font-size: 22px;
  letter-spacing: -0.02em;
}}
.article h3 {{ margin: 25px 0 10px; font-size: 18px; }}
.article h4 {{ margin: 20px 0 8px; font-size: 16px; }}
h1, h2, h3, h4 {{ line-height: 1.35; }}
p, li {{ line-height: 1.9; }}
p {{ margin: 10px 0; }}
ul, ol {{ padding-left: 1.35rem; }}
strong {{ color: #101828; }}
code {{ background: var(--code); color: #344054; padding: 2px 6px; border-radius: 7px; border: 1px solid rgba(148,163,184,.22); font-size: .92em; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: #0b1220; color: #dbeafe; padding: 14px; border-radius: 14px; line-height: 1.65; font-size: 13px; overflow-x: auto; box-shadow: inset 0 0 0 1px rgba(255,255,255,.06); }}
.math-display {{ margin: 18px 0; padding: 18px 16px; background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); border: 1px solid rgba(52,84,209,.18); border-left: 5px solid var(--accent); border-radius: 16px; overflow-x: auto; box-shadow: var(--shadow-soft); }}
.math-inline {{ color: #1d267d; }}
.callout {{ margin: 18px 0; padding: 16px 18px; border-radius: 18px; border: 1px solid var(--border); background: #fff; box-shadow: var(--shadow-soft); }}
.callout-title {{ display: flex; align-items: center; gap: 9px; font-weight: 900; margin-bottom: 8px; }}
.callout-title span {{ display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; color: white; font-size: 13px; }}
.callout-key {{ border-left: 5px solid var(--key); background: linear-gradient(135deg, #eff6ff 0%, #fff 72%); }}
.callout-key .callout-title {{ color: var(--key); }}
.callout-key .callout-title span {{ background: var(--key); }}
.callout-formula {{ border-left: 5px solid var(--formula); background: linear-gradient(135deg, #ecfdf5 0%, #fff 72%); }}
.callout-formula .callout-title {{ color: var(--formula); }}
.callout-formula .callout-title span {{ background: var(--formula); }}
.callout-warn {{ border-left: 5px solid var(--warn); background: linear-gradient(135deg, #fff1f2 0%, #fff 72%); }}
.callout-warn .callout-title {{ color: var(--warn); }}
.callout-warn .callout-title span {{ background: var(--warn); }}
blockquote {{ margin: 16px 0; padding: 12px 16px; border-left: 4px solid #94a3b8; background: rgba(255,255,255,.72); border-radius: 12px; color: #475467; }}
.table-wrap {{ margin: 16px 0; overflow-x: auto; border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow-soft); }}
table {{ width: 100%; border-collapse: collapse; background: white; font-size: 14px; }}
th {{ background: #f1f5ff; color: #1e2a78; text-align: left; font-weight: 850; }}
th, td {{ padding: 11px 12px; border-bottom: 1px solid #eef2f7; vertical-align: top; }}
tr:last-child td {{ border-bottom: 0; }}
.extracted-wrap {{ padding: 0 18px 18px; background: rgba(255,255,255,.72); }}
details {{ border-top: 1px solid var(--border); }}
details summary {{ cursor: pointer; font-weight: 800; padding: 15px 18px; color: #344054; }}
.section-card {{ border: 1px solid var(--border); border-radius: 16px; margin-bottom: 14px; padding: 14px; background: white; box-shadow: 0 8px 22px rgba(15,23,42,.06); }}
.section-card-top {{ display: flex; justify-content: space-between; gap: 10px; align-items: start; margin-bottom: 8px; }}
.section-card h3 {{ margin: 0; font-size: 15px; }}
.equations {{ padding: 0 18px 18px; }}
.equations ul {{ margin-top: 0; }}
.equations li {{ margin: 6px 0; color: #475467; }}
.footer-note {{ padding: 14px 18px 18px; color: var(--muted); font-size: 12px; }}

.callout-review {{ border-left: 5px solid #7f1d1d; background: linear-gradient(135deg, #fff7ed 0%, #fff 72%); }}
.callout-review .callout-title {{ color: #7f1d1d; }}
.callout-review .callout-title span {{ background: #7f1d1d; }}

.callout-idea {{ border-left: 5px solid #6d28d9; background: linear-gradient(135deg, #f5f3ff 0%, #fff 72%); }}
.callout-idea .callout-title {{ color: #6d28d9; }}
.callout-idea .callout-title span {{ background: #6d28d9; }}

.callout-read {{ border-left: 5px solid #0f766e; background: linear-gradient(135deg, #f0fdfa 0%, #fff 72%); }}
.callout-read .callout-title {{ color: #0f766e; }}
.callout-read .callout-title span {{ background: #0f766e; }}
@media (max-width: 1080px) {{
  .layout {{ grid-template-columns: 1fr; }}
  .pdf-pane {{ position: relative; top: 0; }}
  .pane-title {{ top: 0; }}
  .header {{ position: relative; }}
  .pdf-frame-wrap {{ height: 72vh; }}
}}
@media print {{
  .header, .pdf-pane, .pane-title small, .pdf-toolbar, details, .footer-note {{ display: none !important; }}
  .layout {{ display: block; padding: 0; }}
  .pane {{ box-shadow: none; border: 0; }}
}}
</style>
</head>
<body>
<header class="header">
  <div class="header-inner">
    <h1>{html.escape(title)}</h1>
    <div class="meta-row">
      <span class="badge">PDF: {html.escape(pdf_path or 'N/A')}</span>
      <span class="badge">Pages: {html.escape(str(meta.get('page_count', '?')))}</span>
      <span class="badge">Generated: {html.escape(generated_at)}</span>
    </div>
  </div>
</header>
<main class="layout">
  <section class="pane pdf-pane">
    <div class="pane-title">
      <span>原文 PDF / Original Paper</span>
      <div class="pdf-toolbar">
        {f'<a class="button" href="{html.escape(pdf_src)}" target="_blank" rel="noopener">新窗口打开 PDF</a>' if pdf_src else ''}
        <button type="button" class="toolbar-btn" onclick="setPdfPage(1)">回到第 1 页</button>
      </div>
    </div>
    <div class="pdf-frame-wrap">
      {f'<iframe id="pdfFrame" class="pdf-frame" src="{html.escape(pdf_iframe_src)}" title="Original PDF"></iframe>' if pdf_src else '<div class="pdf-empty">没有找到 PDF 路径。请检查 extracted.json 中的 pdf_path 字段。</div>'}
    </div>
    <details>
      <summary>展开 PDF 文本抽取 fallback / Original extracted text</summary>
      <div class="extracted-wrap">{orig_cards}</div>
    </details>
    <details>
      <summary>展开公式候选行 / Equation candidates</summary>
      <div class="equations"><ul>{eq_html}</ul></div>
    </details>
    <div class="footer-note">提示：如果浏览器限制本地 PDF 预览，请点击“新窗口打开 PDF”，或将 HTML 与 PDF 放在同一工作目录下重新生成。</div>
  </section>

  <section class="pane">
    <div class="pane-title">
      <span>中文详读 / Detailed Reading</span>
      <small>公式由 MathJax 渲染</small>
    </div>
    <div class="content article">{analysis_html}</div>
  </section>
</main>
<script>
const PDF_BASE = {json.dumps(pdf_src, ensure_ascii=False)};
function setPdfPage(page) {{
  const n = parseInt(page, 10) || 1;
  const frame = document.getElementById('pdfFrame');
  if (!frame || !PDF_BASE) return;
  frame.src = PDF_BASE + '#page=' + n;
  const pane = document.querySelector('.pdf-pane');
  if (pane) pane.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
}}
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render paper reading HTML.")
    parser.add_argument("--extracted", required=True, help="Path to extracted.json")
    parser.add_argument("--analysis", required=True, help="Path to analysis.md")
    parser.add_argument("--out", required=True, help="Output HTML path")
    parser.add_argument(
        "--mathjax-src",
        default=DEFAULT_MATHJAX_SRC,
        help="MathJax script URL or local path. Default: CDN tex-svg.js",
    )
    args = parser.parse_args()

    extracted_path = Path(args.extracted)
    analysis_path = Path(args.analysis)
    out_path = Path(args.out)
    if not extracted_path.exists():
        raise SystemExit(f"Missing extracted JSON: {extracted_path}")
    if not analysis_path.exists():
        raise SystemExit(f"Missing analysis markdown: {analysis_path}")

    extracted = json.loads(extracted_path.read_text(encoding="utf-8"))
    analysis_md = analysis_path.read_text(encoding="utf-8")
    html_text = render(extracted, analysis_md, mathjax_src=args.mathjax_src)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    print(f"[OK] Wrote HTML: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
