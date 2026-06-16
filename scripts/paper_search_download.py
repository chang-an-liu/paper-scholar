#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_search_download.py

Search academic papers from arXiv and Semantic Scholar, optionally download legal
open-access PDFs, and write a local paper index.

Examples:
  python paper_search_download.py --query "cross-domain few-shot learning" \
    --field "medical image" --from-year 2022 --to-year 2026 \
    --max-results 30 --sources arxiv,s2 --out-dir ./papers --download

Notes:
  - This script downloads only open-access PDFs from arXiv, Semantic Scholar
    openAccessPdf, or Unpaywall OA locations.
  - It never bypasses paywalls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

USER_AGENT = "paper-scholar-skill/0.1 (mailto:example@example.com)"

FIELD_HINTS = {
    "computer vision": ["cs.CV"],
    "cv": ["cs.CV"],
    "machine learning": ["cs.LG", "cs.AI"],
    "deep learning": ["cs.LG", "cs.AI"],
    "medical image": ["eess.IV", "cs.CV", "cs.LG"],
    "medical imaging": ["eess.IV", "cs.CV", "cs.LG"],
    "multimodal": ["cs.CV", "cs.CL", "cs.AI"],
    "multimodal learning": ["cs.CV", "cs.CL", "cs.AI"],
    "few-shot": ["cs.CV", "cs.LG", "cs.AI"],
    "few-shot learning": ["cs.CV", "cs.LG", "cs.AI"],
    "quantum": ["quant-ph", "cs.LG", "cs.ET"],
    "quantum machine learning": ["quant-ph", "cs.LG"],
    "model compression": ["cs.CV", "cs.LG", "cs.AI"],
    "pruning": ["cs.CV", "cs.LG"],
}

CDFSL_CLASSIFICATION_QUERIES = [
    "cross-domain few-shot learning",
    "cross domain few shot classification",
    "CDFSL few-shot classification",
    "cross-domain few-shot classification",
    "Vision Transformer cross-domain few-shot learning",
]

CDFSL_MUST_KEEP_TITLES = [
    "A Closer Look at the CLS Token for Cross-Domain Few-Shot Learning",
    "Cross-domain Few-shot Learning with Task-specific Adapters",
    "Random Registers for Cross-Domain Few-Shot Learning",
    "Reconstruction Target Matters in Masked Image Modeling for Cross-Domain Few-Shot Learning",
]

SEGMENTATION_NOISE_TERMS = [
    "segmentation",
    "semantic segmentation",
    "medical image segmentation",
    "few-shot segmentation",
    "domain generalization segmentation",
    "organ segmentation",
    "tumor segmentation",
    "lesion segmentation",
]


@dataclass
class Paper:
    title: str
    year: Optional[int] = None
    authors: str = ""
    abstract: str = ""
    venue: str = ""
    source: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    pdf_url: str = ""
    is_open_access: Optional[bool] = None
    citation_count: Optional[int] = None
    fields_of_study: str = ""
    local_pdf: str = ""
    download_status: str = "not_requested"
    note: str = ""


def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def is_exact_title_match(candidate_title: str, target_title: str) -> bool:
    """
    Exact title matching after normalization.
    It ignores case, punctuation, spaces, hyphens, colons, etc.
    Example:
      "A Survey on Cross-Domain Few-Shot Learning"
      ==
      "A survey on cross domain few shot learning"
    """
    return normalize_title(candidate_title) == normalize_title(target_title)


def filter_by_exact_title(papers: List[Paper], target_title: str) -> List[Paper]:
    if not target_title:
        return papers
    return [p for p in papers if is_exact_title_match(p.title, target_title)]


def infer_intent(query: str, field: str, title: str = "", explicit: str = "auto") -> str:
    if explicit and explicit != "auto":
        return explicit
    text = f"{query} {field} {title}".lower()
    if "segmentation" in text or "分割" in text:
        return "segmentation"
    if "cross-domain few-shot" in text or "cross domain few shot" in text or "cdfsl" in text:
        return "cdfsl_classification"
    return "generic"


def expanded_queries(query: str, intent: str) -> List[str]:
    query = clean_text(query)
    queries = [query] if query else []
    if intent == "cdfsl_classification":
        queries.extend(CDFSL_CLASSIFICATION_QUERIES)
    out = []
    seen = set()
    for q in queries:
        key = q.lower()
        if q and key not in seen:
            out.append(q)
            seen.add(key)
    return out


def semantic_field_for_intent(field: str, intent: str) -> str:
    """Avoid turning CDFSL classification searches into medical segmentation searches."""
    if intent == "cdfsl_classification":
        field_l = (field or "").lower()
        if any(x in field_l for x in ["medical", "medicine", "segmentation", "医学", "分割"]):
            return "computer vision"
    return field


def paper_relevance_score(p: Paper, query: str, intent: str) -> int:
    text = " ".join([p.title, p.abstract, p.venue, p.fields_of_study]).lower()
    title = p.title.lower()
    score = 0

    for term in re.findall(r"[a-zA-Z][a-zA-Z-]+", query.lower()):
        if len(term) > 2 and term in text:
            score += 1

    if intent == "cdfsl_classification":
        if "cross-domain few-shot" in text or "cross domain few shot" in text:
            score += 20
        if "cdfsl" in text:
            score += 10
        if "few-shot classification" in text or "few shot classification" in text:
            score += 8
        if "cls token" in text or "vision transformer" in text:
            score += 5
        if any(is_exact_title_match(p.title, keep) for keep in CDFSL_MUST_KEEP_TITLES):
            score += 100
        if any(term in text for term in SEGMENTATION_NOISE_TERMS):
            score -= 25
        if "segmentation" in title:
            score -= 35
        if "medical" in title and "classification" not in text:
            score -= 8

    return score


def rerank_papers(papers: List[Paper], query: str, intent: str) -> List[Paper]:
    scored = [(paper_relevance_score(p, query, intent), p) for p in papers]
    scored.sort(key=lambda x: (x[0], x[1].citation_count or 0, x[1].year or 0), reverse=True)
    out = []
    for score, p in scored:
        if intent == "cdfsl_classification" and score < -10:
            p.note = (p.note + "; " if p.note else "") + "low_relevance_for_cdfsl_classification"
        out.append(p)
    return out


def slugify(text: str, max_len: int = 90) -> str:
    text = clean_text(text)
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text).strip("._")
    if not text:
        text = "paper"
    return text[:max_len]


def safe_year(y: object) -> Optional[int]:
    try:
        if y is None:
            return None
        return int(str(y)[:4])
    except Exception:
        return None


def request_get(url: str, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, params=params, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def arxiv_query_from_user(query: str, field: str) -> str:
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if terms:
        q = " AND ".join(f"all:{urllib.parse.quote(t)}" for t in terms[:12])
    else:
        q = "all:*"

    cats = []
    field_l = (field or "").lower().strip()
    for key, values in FIELD_HINTS.items():
        if key in field_l:
            cats.extend(values)
    cats = sorted(set(cats))
    if cats:
        cat_q = " OR ".join(f"cat:{c}" for c in cats)
        q = f"({q}) AND ({cat_q})"
    return q


def parse_arxiv_id(entry_id: str) -> str:
    # e.g. http://arxiv.org/abs/2401.12345v2
    return entry_id.rstrip("/").split("/")[-1]


def search_arxiv(query: str, field: str, max_results: int, from_year: Optional[int], to_year: Optional[int]) -> List[Paper]:
    base = "https://export.arxiv.org/api/query"
    search_query = arxiv_query_from_user(query, field)
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    try:
        r = request_get(base, params=params, timeout=45)
    except Exception as e:
        print(f"[WARN] arXiv search failed: {e}", file=sys.stderr)
        return []

    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(r.text)
    papers: List[Paper] = []
    for entry in root.findall("a:entry", ns):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ns))
        abstract = clean_text(entry.findtext("a:summary", default="", namespaces=ns))
        published = entry.findtext("a:published", default="", namespaces=ns)
        year = safe_year(published)
        if from_year and year and year < from_year:
            continue
        if to_year and year and year > to_year:
            continue
        authors = ", ".join(clean_text(a.findtext("a:name", default="", namespaces=ns)) for a in entry.findall("a:author", ns))
        entry_id = entry.findtext("a:id", default="", namespaces=ns)
        arxiv_id = parse_arxiv_id(entry_id)
        pdf_url = ""
        for link in entry.findall("a:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        primary_cat = ""
        pc = entry.find("arxiv:primary_category", ns)
        if pc is not None:
            primary_cat = pc.attrib.get("term", "")
        papers.append(Paper(
            title=title,
            year=year,
            authors=authors,
            abstract=abstract,
            venue=primary_cat,
            source="arxiv",
            arxiv_id=arxiv_id,
            url=entry_id,
            pdf_url=pdf_url,
            is_open_access=True,
            fields_of_study=primary_cat,
        ))
    return papers


def search_semantic_scholar(query: str, field: str, max_results: int, from_year: Optional[int], to_year: Optional[int], api_key: str = "") -> List[Paper]:
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = ",".join([
        "title", "abstract", "year", "authors", "venue", "citationCount", "url",
        "externalIds", "openAccessPdf", "isOpenAccess", "publicationDate", "fieldsOfStudy", "tldr"
    ])
    q = query
    if field:
        q = f"{query} {field}"
    params = {"query": q, "limit": min(max_results, 100), "fields": fields}
    if from_year and to_year:
        params["year"] = f"{from_year}-{to_year}"
    elif from_year:
        params["year"] = f"{from_year}-"
    elif to_year:
        params["year"] = f"-{to_year}"
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key
    try:
        r = requests.get(endpoint, params=params, headers=headers, timeout=45)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[WARN] Semantic Scholar search failed: {e}", file=sys.stderr)
        return []

    papers: List[Paper] = []
    for item in data.get("data", []):
        title = clean_text(item.get("title"))
        if not title:
            continue
        year = safe_year(item.get("year") or item.get("publicationDate"))
        if from_year and year and year < from_year:
            continue
        if to_year and year and year > to_year:
            continue
        authors = ", ".join(clean_text(a.get("name")) for a in item.get("authors", []) if a.get("name"))
        ext = item.get("externalIds") or {}
        oa = item.get("openAccessPdf") or {}
        pdf_url = clean_text(oa.get("url")) if isinstance(oa, dict) else ""
        fields_s = ", ".join(item.get("fieldsOfStudy") or [])
        tldr = item.get("tldr") or {}
        abstract = clean_text(item.get("abstract") or (tldr.get("text") if isinstance(tldr, dict) else ""))
        papers.append(Paper(
            title=title,
            year=year,
            authors=authors,
            abstract=abstract,
            venue=clean_text(item.get("venue")),
            source="semantic_scholar",
            doi=clean_text(ext.get("DOI")),
            arxiv_id=clean_text(ext.get("ArXiv")),
            url=clean_text(item.get("url")),
            pdf_url=pdf_url,
            is_open_access=item.get("isOpenAccess"),
            citation_count=item.get("citationCount"),
            fields_of_study=fields_s,
        ))
    return papers


def unpaywall_pdf_url(doi: str, email: str) -> str:
    if not doi or not email:
        return ""
    doi_enc = urllib.parse.quote(doi, safe="")
    url = f"https://api.unpaywall.org/v2/{doi_enc}"
    try:
        r = request_get(url, params={"email": email}, timeout=30)
        data = r.json()
    except Exception as e:
        print(f"[WARN] Unpaywall lookup failed for DOI {doi}: {e}", file=sys.stderr)
        return ""
    loc = data.get("best_oa_location") or {}
    if loc.get("url_for_pdf"):
        return clean_text(loc.get("url_for_pdf"))
    for loc in data.get("oa_locations") or []:
        if loc.get("url_for_pdf"):
            return clean_text(loc.get("url_for_pdf"))
    return ""


def dedupe(papers: Iterable[Paper]) -> List[Paper]:
    seen = set()
    out = []
    for p in papers:
        keys = []
        if p.doi:
            keys.append("doi:" + p.doi.lower())
        if p.arxiv_id:
            keys.append("arxiv:" + re.sub(r"v\d+$", "", p.arxiv_id.lower()))
        keys.append("title:" + normalize_title(p.title))
        key = next((k for k in keys if k not in seen), keys[-1])
        if any(k in seen for k in keys):
            # Merge missing pdf_url/open access info into existing record when possible.
            continue
        for k in keys:
            seen.add(k)
        out.append(p)
    return out


def looks_like_pdf(content: bytes, content_type: str) -> bool:
    return content[:4] == b"%PDF" or "pdf" in (content_type or "").lower()


def download_pdf(url: str, dest: Path) -> Tuple[bool, str]:
    if not url:
        return False, "no_pdf_url"
    try:
        headers = {"User-Agent": USER_AGENT}
        with requests.get(url, headers=headers, timeout=60, stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "")
            first = next(r.iter_content(chunk_size=4096), b"")
            if not looks_like_pdf(first, content_type):
                # Some servers return octet-stream; still accept when URL ends with .pdf.
                if not urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
                    return False, f"not_pdf_content_type:{content_type}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(first)
                for chunk in r.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        f.write(chunk)
        if dest.stat().st_size < 1024:
            return False, "download_too_small"
        return True, "downloaded"
    except Exception as e:
        return False, f"download_failed:{e}"


def save_outputs(papers: List[Paper], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "metadata.jsonl"
    csv_path = out_dir / "index.csv"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for p in papers:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    fieldnames = list(asdict(papers[0]).keys()) if papers else list(Paper(title="").__dict__.keys())
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in papers:
            writer.writerow(asdict(p))
    print(f"[OK] Wrote {len(papers)} records")
    print(f"[OK] CSV:   {csv_path}")
    print(f"[OK] JSONL: {jsonl_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Search and legally download academic papers.")
    parser.add_argument("--query", default="", help="Search keywords")
    parser.add_argument("--title", default="", help="Exact paper title search")
    parser.add_argument("--field", default="", help="Broad field/domain hint")
    parser.add_argument("--from-year", type=int, default=None)
    parser.add_argument("--to-year", type=int, default=None)
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--sources", default="arxiv,s2", help="Comma-separated: arxiv,s2")
    parser.add_argument("--out-dir", default="./papers")
    parser.add_argument("--download", action="store_true", help="Download open-access PDFs")
    parser.add_argument(
        "--intent",
        default="auto",
        choices=["auto", "generic", "cdfsl_classification", "segmentation"],
        help="Search intent. Use cdfsl_classification for cross-domain few-shot classification papers.",
    )
    parser.add_argument("--unpaywall-email", default=os.environ.get("UNPAYWALL_EMAIL", ""))
    parser.add_argument("--semantic-scholar-api-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""))
    args = parser.parse_args()

    if not args.query and not args.title:
        parser.error("Please provide either --query or --title.")

    search_text = args.title if args.title else args.query
    intent = infer_intent(args.query, args.field, args.title, args.intent)
    query_list = [search_text] if args.title else expanded_queries(search_text, intent)
    semantic_field = semantic_field_for_intent(args.field, intent)

    out_dir = Path(args.out_dir)
    pdf_dir = out_dir / "pdf"
    sources = {s.strip().lower() for s in args.sources.split(",") if s.strip()}

    all_papers: List[Paper] = []
    per_source_limit = max(args.max_results, 1)
    for q in query_list:
        if "arxiv" in sources:
            print(f"[INFO] Searching arXiv: {q}", file=sys.stderr)
            all_papers.extend(search_arxiv(q, semantic_field, per_source_limit, args.from_year, args.to_year))
            time.sleep(1.0)
        if "s2" in sources or "semantic_scholar" in sources or "semantic" in sources:
            print(f"[INFO] Searching Semantic Scholar: {q}", file=sys.stderr)
            all_papers.extend(search_semantic_scholar(q, semantic_field, per_source_limit, args.from_year, args.to_year, args.semantic_scholar_api_key))
            time.sleep(1.0)


    papers = dedupe(all_papers)

    if args.title:
        papers = filter_by_exact_title(papers, args.title)

    papers = rerank_papers(papers, search_text, intent)
    papers = papers[: args.max_results]

    if args.download:
        for i, p in enumerate(papers, start=1):
            pdf_url = p.pdf_url
            if not pdf_url and p.arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{p.arxiv_id}.pdf"
            if not pdf_url and p.doi and args.unpaywall_email:
                pdf_url = unpaywall_pdf_url(p.doi, args.unpaywall_email)
            if not pdf_url:
                p.download_status = "no_open_pdf_found"
                continue
            year = p.year or "unknown"
            fname = f"{year}_{slugify(p.title)}.pdf"
            dest = pdf_dir / fname
            print(f"[INFO] Downloading {i}/{len(papers)}: {p.title[:80]} -> {dest}", file=sys.stderr)
            ok, status = download_pdf(pdf_url, dest)
            p.pdf_url = pdf_url
            p.download_status = status
            if ok:
                p.local_pdf = str(dest)
            time.sleep(0.7)

    save_outputs(papers, out_dir)

    # Human-readable preview.
    for i, p in enumerate(papers, start=1):
        path = p.local_pdf or "-"
        year = p.year or "?"
        cite = p.citation_count if p.citation_count is not None else "-"
        print(f"{i:02d}. [{year}] {p.title} | {p.source} | cites={cite} | pdf={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
