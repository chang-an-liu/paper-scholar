# paper-scholar Claude Code Skill

A Claude Code skill for academic paper search, legal open-access PDF downloading, PDF extraction, and Chinese deep-reading HTML reports.

## Install

Project-level install:

```bash
mkdir -p .claude/skills
cp -r paper-scholar .claude/skills/paper-scholar
python -m pip install -r .claude/skills/paper-scholar/requirements.txt
```

Personal install:

```bash
mkdir -p ~/.claude/skills
cp -r paper-scholar ~/.claude/skills/paper-scholar
python -m pip install -r ~/.claude/skills/paper-scholar/requirements.txt
```

## Use in Claude Code

```text
/paper-scholar 帮我找 2023-2026 年 cross-domain few-shot learning + medical image 的论文，下载开放获取 PDF 到 ./papers
```

```text
/paper-scholar 阅读 ./papers/pdf/xxx.pdf，生成中文详读 HTML，公式要讲明白
```

## Legal note

This skill only downloads open-access PDFs from legal sources such as arXiv, Semantic Scholar openAccessPdf, or Unpaywall OA locations. It does not bypass paywalls.
