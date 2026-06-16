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
/paper-scholar 搜索并下载 2023-2026 年 cross-domain few-shot learning 的核心分类论文，不要混入分割任务。
```

```text
/paper-scholar 阅读 ./papers/pdf/论文名.pdf，生成中文详读 HTML，包含顶会审稿人四问和三个 research ideas。
```

## Legal note

This skill only downloads open-access PDFs from legal sources such as arXiv, Semantic Scholar openAccessPdf, or Unpaywall OA locations. It does not bypass paywalls.
