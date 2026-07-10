# Theatrum

> **One memory palace. Every agent.**
> **一座记忆宫殿，每个 agent 共用。**

**[English](#english)** | **[中文](#中文)**

---

## English

Your agents solve hard problems every day — then forget everything. Claude Code learns your machine's quirks; Codex re-discovers them tomorrow. Every silo starts from zero.

**Theatrum is a local-first memory control plane for AI agents**: a user-owned second brain where agents deposit *distilled experience*, and any agent retrieves the most useful part of it under a minimal token budget.

No LLM extraction pipeline. No embeddings. No cloud. Just Markdown you can read, an index that rebuilds itself, and one MCP server every agent speaks to.

### Everything serves one call

> **`memory_context(task, budget)` — given the current task and a token budget, return a map plus the most relevant experience.**

The vault, the capture flow, the MCP plumbing — all supply lines for that call. An agent reads ~300 tokens of map, orients itself, and gets exactly the experience it needs. Nothing more.

### Memories are experience, not notes

A memory is a complete experience unit — what broke, what was tried, what worked, what to remember:

```markdown
---
id: 20260710-fts5-chinese
type: lesson
scope: project
tags: [sqlite, fts5, search]
confidence: high
used: 3
dead_end: 0
---

## Problem
FTS5 default tokenizer handles CJK poorly.

## Tried
- jieba custom tokenizer → works, heavy dependency
- unicode61 per-char → too much recall noise

## Worked
FTS5 trigram tokenizer: zero deps, good enough precision.

## Takeaway
Don't add a segmentation library until trigram measurably fails.
```

Plain Markdown is the source of truth. Open the vault in Obsidian, grep it, diff it in Git, edit it by hand — it's yours.

### The knowledge flywheel

```text
solve a problem with an agent
  → remember the experience
  → distill syntheses from it (with derived_from provenance)
  → retrieve it on the next task
  → feedback marks what helped
  → ranking improves
```

Feedback counters (`used` / `dead_end`) feed straight into ranking. The vault compounds with use — a second brain, not an archive.

Theatrum never runs an LLM itself. The intelligence stays on the agent side; Theatrum stores, ranks, and packs.

### The golden scenarios

Four flows the release must make dependable — each one is a test:

1. **Cross-agent recall** — Claude Code saves a project decision; Codex retrieves it in the same project.
2. **Global preferences** — save once, every connected agent uses it across projects.
3. **Hard project isolation** — memory from one project is *never* silently injected into another. A wrong match is worse than no match.
4. **Provenance** — an agent distills a synthesis from earlier memories; `derived_from` links keep the full chain visible in Obsidian.

### Why nothing else fits

Existing agent-memory systems are either heavy (mem0, Letta, Zep — LLM extraction pipelines, vector stores, managed backends) or Markdown-adjacent but embedding-dependent. The combination Theatrum targets is an open gap:

| | Theatrum |
|---|---|
| Canonical store | Plain Markdown, user-owned |
| Extraction | None — agents distill, Theatrum stores |
| Retrieval | SQLite FTS5 (trigram, CJK-friendly) + ranking with floors |
| Sharing | One MCP stdio server, every agent |
| Dependencies | `mcp` + `pyyaml`. That's it. |
| Network | None. Local stdio, no listening port |

Vector search and knowledge graphs stay optional, derived, and *later* — added only when FTS5 provably falls short, without changing who owns the memory.

### Quick start

```bash
git clone <this repo> && cd Theatrum
uv venv && uv pip install -e .

theatrum init                  # vault at ~/.theatrum/vault
theatrum connect claude        # wires the MCP server into Claude Code
theatrum connect codex         # ...and Codex (config backed up first, always)

# save your first experience
theatrum remember "## Problem
...
## Takeaway
..." --type lesson --scope global --title "my first lesson"

theatrum recall "that thing about ..."
theatrum context "current task description" --budget 2000
```

Every host-config edit is backed up first, and `disconnect` fully reverses `connect`.

### Design rules

- **Markdown is canonical; every index is disposable.** Delete `index.db` — it rebuilds from the vault.
- **Scope isolation is a hard filter, not a ranking boost.**
- **Explicit capture.** User-requested memories go live; agent-inferred ones wait in `inbox/` for your review.
- **Git is the audit trail.** History, review, rollback with tools you already know.

### Status

**S1 vertical slice shipped**: vault + `remember`/`recall`/`context` CLI + 4 MCP tools + Claude Code / Codex connect. Golden scenarios 1–3 pass as tests against an isolated `$HOME`; the MCP protocol layer is tested end-to-end over real stdio.

Next: inbox review flow (S2), read-only importers for existing agent memories (S3), pipx distribution (S4).

Read the [V1 Master Plan](docs/V1_MASTER_PLAN.md) and [Project Anchor](docs/PROJECT_ANCHOR.md) for the boundaries that guide the design.

---

## 中文

你的 agent 每天都在解决难题——然后全部忘掉。Claude Code 摸清了你机器的坑，Codex 明天从头再踩一遍。每个孤岛都从零开始。

**Theatrum 是一个本地优先的 agent 记忆控制平面**：一个用户自有的第二大脑。agent 把*提炼后的经验*存进来，任何 agent 都能在极小的 token 预算内取走最有用的那部分。

没有 LLM 抽取管线，没有向量嵌入，没有云端。只有你读得懂的 Markdown、随时可重建的索引，和一个所有 agent 都能对话的 MCP 服务器。

### 一切服务于一个调用

> **`memory_context(task, budget)` —— 给定当前任务和 token 预算，返回一张地图和最相关的经验。**

vault、采集流程、MCP 管线——都是这个调用的补给线。agent 先读约 300 token 的地图定位全局，然后拿到恰好需要的经验，一个字不多。

### 记忆是经验，不是笔记

一条记忆是完整的经验单元——什么坏了、试过什么、什么有效、该记住什么：

```markdown
---
id: 20260710-fts5-chinese
type: lesson
scope: project
tags: [sqlite, fts5, search]
confidence: high
used: 3
dead_end: 0
---

## Problem
FTS5 默认分词器对中日韩文本支持很差。

## Tried
- jieba 自定义分词器 → 可用，但依赖太重
- unicode61 按字切分 → 召回噪音过大

## Worked
FTS5 trigram 分词器：零依赖，精度够用。

## Takeaway
在 trigram 被证明不够用之前，不要引入分词库。
```

纯 Markdown 就是唯一事实。用 Obsidian 打开、grep 检索、Git 审计、亲手编辑——它是你的。

### 知识飞轮

```text
和 agent 一起解决问题
  → 沉淀经验
  → 提炼综合结论（带 derived_from 溯源）
  → 下次任务直接取用
  → 反馈标记哪些真正有用
  → 排序越用越准
```

反馈计数（`used` / `dead_end`）直接进入排序公式。vault 越用越强——是第二大脑，不是归档柜。

Theatrum 自己从不调用 LLM。智能留在 agent 一侧；Theatrum 只负责存储、排序、打包。

### 黄金场景

发布必须保证的四条链路——每一条都是测试：

1. **跨 agent 召回** —— Claude Code 存下项目决策，Codex 在同一项目里取回。
2. **全局偏好** —— 存一次，所有已接入的 agent 跨项目可用。
3. **项目硬隔离** —— 一个项目的记忆*绝不*悄悄注入另一个项目。错误匹配比没有匹配更糟。
4. **可溯源** —— agent 从既有记忆提炼综合结论，`derived_from` 链路在 Obsidian 里完整可见。

### 为什么现有方案都不合适

现有 agent 记忆系统要么太重（mem0、Letta、Zep——LLM 抽取管线、向量库、托管后端），要么接近 Markdown 但依赖 embedding。Theatrum 瞄准的组合目前是空白：

| | Theatrum |
|---|---|
| 事实源 | 纯 Markdown，用户自有 |
| 抽取 | 无——agent 提炼，Theatrum 存储 |
| 检索 | SQLite FTS5（trigram，中文友好）+ 带下限的排序公式 |
| 共享 | 一个 MCP stdio 服务器，所有 agent |
| 依赖 | `mcp` + `pyyaml`，就这两个 |
| 网络 | 无。本地 stdio，不开端口 |

向量检索和知识图谱是可选的、派生的、*以后的事*——只在 FTS5 被证明不够用时加入，且不改变记忆的所有权。

### 快速开始

```bash
git clone <this repo> && cd Theatrum
uv venv && uv pip install -e .

theatrum init                  # vault 建在 ~/.theatrum/vault
theatrum connect claude        # 把 MCP 服务器接入 Claude Code
theatrum connect codex         # ……以及 Codex（改配置前必先备份）

# 存下第一条经验
theatrum remember "## Problem
...
## Takeaway
..." --type lesson --scope global --title "my first lesson"

theatrum recall "那个关于……的东西"
theatrum context "当前任务描述" --budget 2000
```

每次修改宿主配置前都会先备份，`disconnect` 可完全还原 `connect`。

### 设计准则

- **Markdown 是唯一事实；所有索引皆可抛弃。** 删掉 `index.db`，它会从 vault 自动重建。
- **作用域隔离是硬过滤器，不是排序加权。**
- **显式采集。** 用户要求的记忆立即生效；agent 自行推断的进 `inbox/` 等你审核。
- **Git 就是审计日志。** 用你已经熟悉的工具查看历史、审核、回滚。

### 状态

**S1 垂直切片已交付**：vault + `remember`/`recall`/`context` CLI + 4 个 MCP 工具 + Claude Code / Codex 接入。黄金场景 1–3 已在隔离 `$HOME` 下通过测试；MCP 协议层经真实 stdio 端到端验证。

下一步：inbox 审核流（S2）、既有 agent 记忆的只读导入器（S3）、pipx 分发（S4）。

设计边界详见 [V1 Master Plan](docs/V1_MASTER_PLAN.md) 与 [Project Anchor](docs/PROJECT_ANCHOR.md)。
