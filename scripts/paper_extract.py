#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_extract.py

Extract text from a PDF into Markdown and JSON files for deep reading.

Outputs:
  - original.md: page-by-page original extracted text
  - sections.md: heuristic section split
  - equation_candidates.md: lines likely containing formulas/equations
  - extracted.json: structured data for HTML rendering
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import fitz  # PyMuPDF
except Exception as e:  # pragma: no cover
    raise SystemExit("PyMuPDF is required. Install with: python -m pip install PyMuPDF") from e


SECTION_PATTERNS = [
    r"abstract", r"introduction", r"related work", r"background", r"preliminaries",
    r"method", r"methodology", r"approach", r"model", r"framework",
    r"experiments?", r"results?", r"discussion", r"ablation", r"analysis",
    r"conclusion", r"limitations?", r"appendix", r"references",
]

EQUATION_SYMBOL_RE = re.compile(
    r"(=|≤|≥|≈|≜|:=|\barg\s*min\b|\barg\s*max\b|\bsum\b|\bprod\b|∑|∏|∫|√|∞|∂|∇|\bL\s*\(|\bloss\b|\bsoftmax\b|\blog\b|\bexp\b|\bKL\b|\bCE\b|\bmin\b|\bmax\b)",
    flags=re.IGNORECASE,
)


@dataclass
class PageText:
    page: int
    text: str


@dataclass
class Section:
    title: str
    start_page: int
    text: str


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(pdf_path: Path) -> Tuple[Dict, List[PageText]]:
    doc = fitz.open(str(pdf_path))
    meta = dict(doc.metadata or {})
    pages: List[PageText] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages.append(PageText(page=i, text=clean_text(text)))
    meta["page_count"] = len(pages)
    return meta, pages


def is_section_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 120:
        return False
    low = s.lower().strip(" .:-—")
    if any(re.fullmatch(p, low) for p in SECTION_PATTERNS):
        return True
    if re.match(r"^(\d+|[ivx]+)(\.\d+)*[\s.:-]+[A-Z][A-Za-z0-9 ,:/()\-]{2,100}$", s):
        return True
    if re.match(r"^[A-Z][A-Z0-9 ,:/()\-]{4,100}$", s) and len(s.split()) <= 10:
        return True
    return False


def split_sections(pages: List[PageText]) -> List[Section]:
    sections: List[Section] = []
    current_title = "Front Matter / Unsectioned"
    current_start = pages[0].page if pages else 1
    buf: List[str] = []

    for p in pages:
        for line in p.text.splitlines():
            line_s = line.strip()
            if is_section_heading(line_s):
                if buf:
                    sections.append(Section(current_title, current_start, clean_text("\n".join(buf))))
                current_title = line_s
                current_start = p.page
                buf = [f"[Page {p.page}]", line_s]
            else:
                if line_s:
                    buf.append(line_s)
        buf.append("")
    if buf:
        sections.append(Section(current_title, current_start, clean_text("\n".join(buf))))

    # Fallback: if section detection is too fragmented or too weak, use page chunks.
    if len(sections) <= 2 or len(sections) > 80:
        sections = [Section(title=f"Page {p.page}", start_page=p.page, text=p.text) for p in pages]
    return sections


def find_equation_candidates(pages: List[PageText]) -> List[Dict]:
    candidates = []
    for p in pages:
        for line_no, line in enumerate(p.text.splitlines(), start=1):
            s = line.strip()
            if 8 <= len(s) <= 260 and EQUATION_SYMBOL_RE.search(s):
                # Avoid table-of-content/reference noise as much as possible.
                if re.search(r"doi|isbn|http|www\.", s, flags=re.IGNORECASE):
                    continue
                candidates.append({"page": p.page, "line": line_no, "text": s})
    return candidates[:300]


def write_outputs(pdf_path: Path, out_dir: Path, meta: Dict, pages: List[PageText], sections: List[Section], equations: List[Dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    original_md = out_dir / "original.md"
    with open(original_md, "w", encoding="utf-8") as f:
        f.write(f"# Original extracted text\n\nPDF: `{pdf_path}`\n\n")
        for p in pages:
            f.write(f"\n\n## Page {p.page}\n\n")
            f.write(p.text or "[No text extracted]")
            f.write("\n")

    sections_md = out_dir / "sections.md"
    with open(sections_md, "w", encoding="utf-8") as f:
        f.write(f"# Section-level extracted text\n\nPDF: `{pdf_path}`\n\n")
        for sec in sections:
            f.write(f"\n\n## {sec.title}\n\n_Start page: {sec.start_page}_\n\n")
            f.write(sec.text or "[No text extracted]")
            f.write("\n")

    eq_md = out_dir / "equation_candidates.md"
    with open(eq_md, "w", encoding="utf-8") as f:
        f.write("# Equation / formula candidates\n\n")
        if not equations:
            f.write("No obvious equation candidates were detected from PDF text extraction.\n")
        for item in equations:
            f.write(f"- Page {item['page']}, line {item['line']}: {item['text']}\n")

    data = {
        "pdf_path": str(pdf_path),
        "metadata": meta,
        "pages": [asdict(p) for p in pages],
        "sections": [asdict(s) for s in sections],
        "equation_candidates": equations,
    }
    with open(out_dir / "extracted.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] Extracted {len(pages)} pages into {out_dir}")
    print(f"[OK] {original_md}")
    print(f"[OK] {sections_md}")
    print(f"[OK] {eq_md}")
    print(f"[OK] {out_dir / 'extracted.json'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract PDF text for deep paper reading.")
    parser.add_argument("--pdf", required=True, help="Path to PDF")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    out_dir = Path(args.out_dir)
    meta, pages = extract_pages(pdf_path)
    sections = split_sections(pages)
    equations = find_equation_candidates(pages)
    write_outputs(pdf_path, out_dir, meta, pages, sections, equations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
