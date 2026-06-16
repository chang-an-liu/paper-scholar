---
name: paper-scholar
description: Search, legally download, organize, and deeply read academic papers. Use when the user asks to find recent papers by keyword, research field, timeline, exact paper title, or wants to read a local PDF with the original PDF on the left and a detailed Chinese explanation on the right in a polished HTML report.
allowed-tools: Bash Read Write Edit Glob Grep
---

# Paper Scholar

Use this skill to help the user build a local paper library and deeply read papers.

The skill has two jobs:

1. **Search and legally download papers** into a local folder by keyword, exact paper title, broad research direction, venue/topic, and year range.
2. **Deeply read a downloaded/local paper** and generate a polished HTML report. The report should show the original PDF on the left and the detailed Chinese reading on the right. Important ideas, formulas, warnings, and page links should be clearly marked.

Never use Sci-Hub, credential bypass, shadow libraries, or any method that evades publisher access control. Download only open-access PDFs found from arXiv, official open PDFs, Semantic Scholar `openAccessPdf`, or Unpaywall open-access locations.

## Default folders

Use these defaults unless the user specifies otherwise:

- Paper library: `./papers/`
- PDF folder: `./papers/pdf/`
- Metadata files: `./papers/index.csv` and `./papers/metadata.jsonl`
- Reading outputs: `./paper_readings/<paper-slug>/`
- Final HTML: `./paper_readings/<paper-slug>/reading.html`

## Setup check

Before running scripts for the first time in a project, check dependencies:

```bash
python -m pip install -r .claude/skills/paper-scholar/requirements.txt
```

If this is a personal skill under `~/.claude/skills/paper-scholar/`, use that path instead.

## Workflow A: search and download papers

When the user asks to search papers, infer:

- `query`: exact keyword(s), e.g. `cross-domain few-shot learning medical image`
- `title`: exact paper title when the user gives a specific paper name.
- `field`: broad area, e.g. `computer vision`, `medical image`, `multimodal learning`, `quantum machine learning`, `model compression`
- `intent`: if the user says `cross-domain few-shot learning`, `cross domain few shot learning`, or `CDFSL` without explicitly saying segmentation, set `intent` to `cdfsl_classification`.
- `from-year` and `to-year`: if unspecified, use the most recent 3 years.
- `max-results`: if unspecified, use 30.
- `download`: default to metadata search only unless the user explicitly asks to download. If the user asks to download, download only legal open-access PDFs.

### CDFSL search intent rule

Do not automatically add `medical image`, `medical imaging`, or `segmentation` to a Cross-Domain Few-Shot Learning query just because the user often works on medical images.

For `cross-domain few-shot learning` / `CDFSL`, treat the default task as **few-shot classification**, not segmentation. Use `--intent cdfsl_classification` and prefer broad computer-vision queries:

```bash
python .claude/skills/paper-scholar/scripts/paper_search_download.py \
  --query "cross-domain few-shot learning" \
  --intent cdfsl_classification \
  --field "computer vision" \
  --from-year "$FROM_YEAR" \
  --to-year "$TO_YEAR" \
  --max-results "$MAX_RESULTS" \
  --sources arxiv,s2 \
  --out-dir ./papers
```

Only use `--field "medical image"` or segmentation-oriented terms when the user explicitly asks for medical CDFSL, medical image classification, or few-shot segmentation.

For CDFSL classification, ensure the candidate list includes or checks for core papers such as:

- `A Closer Look at the CLS Token for Cross-Domain Few-Shot Learning`
- `Cross-domain Few-shot Learning with Task-specific Adapters`
- `Random Registers for Cross-Domain Few-Shot Learning`
- `Reconstruction Target Matters in Masked Image Modeling for Cross-Domain Few-Shot Learning`

If these papers are missing, run an exact-title search for the missing title before reporting results.

If exact-title search returns zero records, do not conclude that the paper does not exist. Fall back to official-source lookup by the exact title:

1. Search official venues first: NeurIPS Proceedings, OpenReview, CVF/OpenAccess, PMLR, AAAI/IJCAI/ICLR official pages, arXiv.
2. Prefer official PDF links from the venue page or OpenReview.
3. If a legal PDF is available, download it manually into `./papers/pdf/` and append a metadata row to `index.csv` / `metadata.jsonl`.
4. If only metadata is available, report the official page and mark `download_status=no_open_pdf_found`.

### Exact title search

When the user provides a specific paper title, use exact title search instead of broad keyword search.

Use:

```bash
python .claude/skills/paper-scholar/scripts/paper_search_download.py \
  --title "$TITLE" \
  --sources arxiv,s2 \
  --out-dir ./papers \
  --download
```

The script should first search candidate papers from arXiv and Semantic Scholar, then keep only records whose normalized title exactly matches the given title. Normalization should ignore case, spaces, punctuation, hyphens, and colons.

### Keyword or research-field search

For normal keyword or research-field search, run:

```bash
python .claude/skills/paper-scholar/scripts/paper_search_download.py \
  --query "$QUERY" \
  --intent "$INTENT" \
  --field "$FIELD" \
  --from-year "$FROM_YEAR" \
  --to-year "$TO_YEAR" \
  --max-results "$MAX_RESULTS" \
  --sources arxiv,s2 \
  --out-dir ./papers \
  --download
```

If using Unpaywall for DOI-based open-access PDF lookup, include a real email:

```bash
--unpaywall-email "your_email@example.com"
```

After search/download:

1. Read `./papers/index.csv`.
2. Report a concise table: title, year, venue/source, citation count if available, open PDF status, local PDF path.
3. Highlight papers that look most relevant to the user's actual research goal.
4. Ask before downloading very large batches, unless the user already specified a number.

## Workflow B: deeply read one local PDF

When the user specifies a paper path, title, or index row:

1. Locate the PDF with `Glob`/`Grep` if needed.
2. Extract text:

```bash
python .claude/skills/paper-scholar/scripts/paper_extract.py \
  --pdf "$PDF_PATH" \
  --out-dir "./paper_readings/$PAPER_SLUG"
```

3. Read these generated files:
   - `original.md`: page-by-page original extracted text.
   - `sections.md`: section-level text when section headings can be detected.
   - `equation_candidates.md`: lines likely containing formulas or mathematical definitions.
   - `extracted.json`: structured extraction for rendering.
4. Produce `analysis.md` using `templates/reading_schema.md` as the structure.

5. Before ordinary summarization, write a reviewer-grade section named `顶会审稿人四问`. It must answer:
   - What problem is the paper truly trying to solve?
   - What contributions do the authors claim?
   - What points are easiest for top-conference reviewers to attack?
   - As a graduate student in the same direction, which parts should be read carefully and which parts can be skipped first?

6. After `顶会审稿人四问`, write `基于不足的三个 Research Ideas`. Each idea must include:
   - weakness it comes from;
   - core hypothesis;
   - possible method design;
   - minimum validation experiment;
   - expected risk or reviewer concern;
   - why it could become publishable.

7. Explain formulas and specialized concepts in Chinese. Use this pattern:
   - Original formula in valid LaTeX.
   - What each variable means.
   - Why the formula is needed in the method.
   - A small numeric or intuitive example.
   - How it affects the model/experiment/result.
8. Render HTML:

```bash
python .claude/skills/paper-scholar/scripts/paper_render_html.py \
  --extracted "./paper_readings/$PAPER_SLUG/extracted.json" \
  --analysis "./paper_readings/$PAPER_SLUG/analysis.md" \
  --out "./paper_readings/$PAPER_SLUG/reading.html"
```

9. Tell the user the HTML path and summarize the most important conclusions.

## HTML report standard

The final `reading.html` must be useful as a browser-based reading workspace:

- Left pane: show the original PDF directly through the browser PDF viewer.
- Right pane: show the detailed Chinese reading.
- Keep extracted text as a collapsible fallback under the PDF pane.
- Render mathematical formulas through MathJax; do not display raw LaTeX as plain text.
- Use beautiful, readable cards for key insights, formulas, and warnings.
- When discussing an important point, include a source-page jump link such as `[[pdf:5|查看原文 Page 5]]` whenever possible.

### Formula rendering rules

When generating `analysis.md`, write all formulas in valid LaTeX.

Use display math for important equations:

```md
$$
\mathbf{v}'_t = \mathbf{v}_t - \beta \cdot \mathbf{t}
$$
```

Use inline math for variables, such as $\mathbf{v}_t$, $\beta$, $\tau$, $\rho$, and $\gamma$.

Do not wrap formulas with backticks.
Do not write formulas as plain text.
Do not use Python-style expressions such as `beta * t` or `vt.T @ t` unless explicitly explaining implementation code.

Every important formula must include:

1. Original LaTeX formula.
2. Symbol explanation.
3. Plain-language interpretation.
4. A simple numerical or intuitive example when useful.

### Highlight markup

Use these blockquote tags in `analysis.md` to create highlighted cards in the final HTML:

```md
> [!KEY] [[pdf:3|查看原文 Page 3]] 这是论文最核心的反直觉发现：tail token 不应该被强制对齐。
```

```md
> [!FORMULA] [[pdf:5|查看原文 Page 5]] 这个公式负责计算 token 与类别文本之间的余弦相似度。
```

```md
> [!WARN] [[pdf:8|查看原文 Page 8]] 这里可能存在一个潜在问题：tail token 是否一定代表无语义噪声？
```

```md
> [!REVIEW] [[pdf:4|查看原文 Page 4]] 如果我是审稿人，我会质疑这里的假设是否被充分验证。
```

```md
> [!IDEA] 基于这个不足，可以做一个新的 research idea：用更强的跨域验证来检验方法是否真的泛化。
```

```md
> [!READ] 这部分建议精读，因为它决定了方法是否真的成立；附录中的实现细节可以先跳过。
```

The renderer will convert `[[pdf:PAGE|TEXT]]` into a button. Clicking the button jumps the left PDF pane to that page.

## Reading standard

For deep reading, do not merely summarize. The output must answer:

- This paper solves what problem?
- Why previous methods are insufficient?
- What is the key idea in one sentence?
- What is the full pipeline?
- What are the key formulas and what do they mean?
- What experiments prove the claim?
- What is actually novel, and what may be incremental?
- What assumptions or weaknesses exist?
- How could the user reuse or challenge this idea in their own work?

For the user, prefer Chinese explanations. Keep original terms such as `prototype`, `alignment`, `contrastive loss`, `information bottleneck`, `cross-domain few-shot learning` alongside Chinese translations when useful.

## Safety and quality rules

- Download only open-access PDFs.
- Do not claim that a paywalled PDF has been downloaded if only metadata was found.
- Preserve DOI, arXiv ID, source URL, and access URL in metadata.
- Deduplicate papers by DOI, arXiv ID, and normalized title.
- If PDF text extraction is poor, say so and still produce a best-effort reading from available text.
- For formulas, acknowledge when the PDF extraction lost symbols; infer carefully and flag uncertainty.
- Prefer newer papers when the user asks for recent work, but do not ignore classic baselines if they are necessary to understand the field.
