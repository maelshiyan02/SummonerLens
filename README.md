# SummonerLens · 召唤师数据分析助手

> 英雄联盟（LOL）数据分析工具。当前阶段深度聚焦「海克斯大乱斗」（官方英文名 **ARAM Mayhem**），
> 未来逐步扩展到「召唤师峡谷」（Summoner's Rift）。命名刻意统合全模式（Summoner 统合所有模式，Lens=洞察）。

## 项目身份（对话中统一识别）

- **英文项目名（唯一）**：`SummonerLens`
- **正式中文名（唯一）**：`召唤师数据分析助手`
- **简略称呼（均指本项目）**：数据分析软件、本项目数据分析助手、本项目、这个工具、我们的工具
- **GitHub 仓库**：`git@github.com:maelshiyan02/SummonerLens.git`（SSH，public）
- **工作区根目录**：`D:\SummonerLens_Windows`

## 技术栈（详见 `.agent` 记忆）

Flutter Desktop（壳） + Python（pandas/polars/duckdb/scipy 数据层） + ECharts（可视化，webview 嵌入）。**本地优先、零后端、可离线**。

## Agent 接入约定

1. 新对话开始：粘贴「新对话开场白」作为上下文（身份 + 协作约定 + 默认规则）。
2. 读取本仓库记忆主文件：`.agent/memory/MEMORY.md`（框架 + 索引 + 底线）。
3. 按索引里的「触发时机」读对应附录 `.agent/memory/appendices/A0x`。
4. 做设计/验证/交接类决策时，读 `.agent/kb/INDEX.md` 挑对应方法论。
5. 查历史决策来龙去脉，看 `.agent/memory/appendices/W00-工作日志索引.md`。

> 记忆真身唯一在 **`.agent/`**，其余（`.workbuddy` 等）是工具自身运行目录，**不**作为项目记忆载体。
> 与 mangrove 项目（D:\Mangrove_Windows）严格隔离：禁止互相改文件。

## 目录结构

```
SummonerLens_Windows/
├─ .agent/                 # 项目记忆唯一真身（见下）
├─ README.md               # 本文件
└─ （后续）源码 / 数据 / 构建产物
```
