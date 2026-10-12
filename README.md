# SummonerLens · 召唤师数据分析助手

> 英雄联盟（LOL）数据分析工具。当前阶段深度聚焦「海克斯大乱斗」（官方英文名 **ARAM Mayhem**），
> 未来逐步扩展到「召唤师峡谷」（Summoner's Rift）。命名刻意统合全模式（Summoner 统合所有模式，Lens=洞察）。

## 项目身份（对话中统一识别）

- **英文项目名（唯一）**：`SummonerLens`
- **正式中文名（唯一）**：`召唤师数据分析助手`
- **简略称呼（均指本项目）**：数据分析软件、本项目数据分析助手、本项目、这个工具、我们的工具
- **GitHub 仓库**：`git@github.com:maelshiyan02/SummonerLens.git`（SSH，public）
- **工作区根目录**：`<项目根>`（位于「AI Coding Project Management」大工作区内；路径可能改名，一律用相对路径）

## 技术栈（详见 `.agent` 记忆）

Flutter Desktop（壳） + Python（pandas/polars/duckdb/scipy 数据层） + ECharts（可视化，webview 嵌入）。**本地优先、零后端、可离线**。

## Agent 接入约定

1. 新对话开始：粘贴「新对话开场白」作为上下文（身份 + 协作约定 + 默认规则）。
2. 读取本仓库记忆主文件：`.agent/memory/MEMORY.md`（框架 + 索引 + 底线）。
3. 按索引里的「触发时机」读对应附录 `.agent/memory/appendices/A0x`。
4. 做设计/验证/交接类决策时，读 `.agent/kb/INDEX.md` 挑对应方法论。
5. 查历史决策来龙去脉，看 `.agent/memory/appendices/W00-工作日志索引.md`。

> 记忆真身唯一在 **`.agent/`**，其余（`.workbuddy` 等）是工具自身运行目录，**不**作为项目记忆载体。
> 与 mangrove 项目（大工作区内同级目录 `../Mangrove`）严格隔离：禁止互相改文件。

## 快速开始（打开仪表板）

在 M4 产物已就绪的前提下，**双击项目根目录下的脚本**即可：

| 方式 | 双击这个文件 | 说明 |
|---|---|---|
| 浏览器（推荐） | `run_dashboard.bat` | 自动起本地服务（随机空闲端口）并打开默认浏览器；**关闭该窗口即停止服务** |
| 桌面壳 | `run_desktop.bat` | 启动 Flutter 桌面程序 `app/build/windows/x64/runner/Release/summonerlens.exe` |
| 离线兜底 | `app/web/index.html` | 直接双击，**无需服务、无需 Python**（数据为上次构建的内联快照） |

- 脚本会自动探测 Python（托管 venv → 系统 `C:\Python38` → PATH 里的 `py`/`python`）。
- 前置：数据束缺失时先跑 `python python/bridge/build_viz_bundle.py`；桌面壳未构建时先跑 `python tools/flutter_task.py build`。
- 无 Python 也能看：直接用「离线兜底」方式。

## 目录结构

```
SummonerLens/
├─ .agent/                 # 项目记忆唯一真身（见下）
├─ README.md               # 本文件
└─ （后续）源码 / 数据 / 构建产物
```
