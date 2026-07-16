---
id: 20260711-fts5-trigram-vs-jieba-for-cjk
type: lesson
scope: project
project: github.com/acme/webapp
tags:
- fts5
- cjk
- search
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from: []
superseded_by: null
used: 0
dead_end: 0
title: FTS5 trigram vs jieba for CJK
---
Use FTS5 trigram tokenizer for CJK search; do not rely on jieba.

Problem: default FTS5 unicode61 tokenizer splits Chinese text on whitespace, so 中文搜索 indexes as one opaque token and single-character queries miss.
Tried: jieba word segmentation — extra dep, model files, and non-deterministic across versions.
Worked: FTS5 built-in trigram tokenizer indexes every 3-char window; recall on 2-3 char queries jumps from ~0% to usable, zero extra deps.
Takeaway: for CJK full-text search, trigram beats word-segmentation when your dependency budget is tight.
