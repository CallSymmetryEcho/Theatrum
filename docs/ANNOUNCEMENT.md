# Theatrum — launch copy

Screenshot slot: `assets/graph.png` (Obsidian knowledge graph of `examples/demo-vault`).

---

## EN — X/Twitter thread

**1/**
Your AI agents solve hard problems every day — then forget everything.
Claude Code learns your machine's quirks. Codex re-discovers them tomorrow. Every agent is a silo that starts from zero.

I built Theatrum: **one memory palace, every agent.**

**2/**
Agents deposit *distilled experience* — what broke, what was tried, what worked — and any agent retrieves the most useful part under a token budget.

One MCP call does all the work:
`memory_context(task, budget)` → a ~300-token map + exactly the experience you need.

**3/**
What it is NOT:
- no LLM extraction pipeline
- no embeddings, no vector DB
- no cloud, no listening port

Just plain Markdown you can grep, diff in Git, and open in Obsidian. Two dependencies. The memory is *yours*.

**4/**
This actually happened during testing:
Codex retrieved a memory Claude Code had saved that morning — "the default python3 on this machine is broken."
The very next command failed… because of exactly that.
The memory palace warned us about the bug before we re-hit it. Cross-agent recall, live.

**5/**
Try it in 5 minutes:

```
pipx install "git+https://github.com/CallSymmetryEcho/Theatrum"
theatrum init && theatrum connect claude && theatrum connect codex
bash examples/demo.sh
```

Then open `examples/demo-vault` in Obsidian and watch the knowledge graph light up.

[screenshot]

**6/**
Already using an agent with piles of old memory files? Migrate, don't retype:

`theatrum import claude ./_claude_memory --scope project`

Read-only, dry-run by default, secrets filtered, dedup'd, full provenance. Everything lands in an inbox — *you* approve what becomes retrievable.

github.com/CallSymmetryEcho/Theatrum

---

## EN — one-liner (HN / Show HN title)

Show HN: Theatrum — a local-first, Markdown-native memory shared by all your AI agents (no embeddings, no cloud, one MCP server)

---

## 中文 — 长文（微博 / 即刻 / V2EX）

你的 AI agent 每天都在解决难题——然后全部忘掉。
Claude Code 摸清了你机器上的坑，Codex 明天从头再踩一遍。每个 agent 都是从零开始的孤岛。

所以我做了 **Theatrum：一座记忆宫殿，每个 agent 共用。**

它是一个本地优先的 agent 记忆控制平面：agent 把*提炼后的经验*（什么坏了、试过什么、什么有效）存进来，任何 agent 通过一个 MCP 调用取走最有用的那部分——
`memory_context(任务, token预算)` → 一张 300 token 的地图 + 恰好需要的经验，一个字不多。

它**不是**什么：
- 没有 LLM 抽取管线
- 没有向量嵌入、没有向量库
- 没有云端、不开网络端口

只有纯 Markdown——你可以 grep、用 Git 审计、在 Obsidian 里打开知识图谱、亲手编辑。运行时依赖只有两个。记忆是你的，不是平台的。

一个真实瞬间：验收那天，Codex 通过 MCP 取回了 Claude Code 早上存的一条记忆——「这台机器的默认 python3 是坏的」。下一条命令的报错，恰好就是这件事。记忆宫殿在我们重新踩坑之前先喊住了我们。

5 分钟上手：

```
pipx install "git+https://github.com/CallSymmetryEcho/Theatrum"
theatrum init && theatrum connect claude && theatrum connect codex
bash examples/demo.sh
```

跑完打开 examples/demo-vault 的 Obsidian 知识图谱，看经验怎么连成树（synthesis 带 derived_from 溯源链）。

已有一堆旧的 agent 记忆文件？不用手搬：
`theatrum import claude ./_claude_memory` ——只读导入、默认 dry-run、自动过滤密钥、内容去重、逐文件溯源，全部先进 inbox 等你审核。

[截图]

repo：github.com/CallSymmetryEcho/Theatrum

---

## 中文 — 短版（朋友圈 / 一条微博）

给所有 AI agent 造了一座共用的记忆宫殿：Theatrum。
Claude Code 存的经验，Codex 直接取用。纯 Markdown、本地优先、零嵌入零云端，Obsidian 打开就是知识图谱。
`pipx install` 一条命令，5 分钟跑通 demo。
github.com/CallSymmetryEcho/Theatrum [截图]
