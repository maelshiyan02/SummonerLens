# data · 本地数据层

> 本地优先：数据落本地（SQLite / DuckDB / Parquet），统计与建模全在本地跑。
> 重型产物（raw JSON / champions_full.json）**不入仓**，可由 `python/etl` 重新抓取；小表随仓便于跨版本 diff。

## 目录结构

```
data/
├─ meta/<version>/             # Data Dragon 版本快照（每 patch 一份）
│  ├─ raw/                     # 原始 JSON（versions / champion / items / 英雄详情 / cdragon 强化符文）[gitignore]
│  ├─ champions_full.json      # 英雄完整数据（含技能/被动）[gitignore，大]
│  ├─ champions.csv            # 英雄基础表
│  ├─ items.csv                # 装备表（Data Dragon 原样）
│  ├─ items_modes.csv          # 装备表 + 模式归属（maps/modes/id_family/aram_mode…，见 A12）
│  ├─ item_modes_summary.json  # 模式归属汇总 + DD↔CDragon 一致性核验
│  ├─ aram_mayhem_items.json   # 海克斯大乱斗专属/相关装备清单（含 scope/confidence/证据）
│  ├─ skill_archetypes.csv     # 技能原型标注表（7 标签：auto + 人工校订 manual_tags，见 A11）
│  ├─ archetype_overrides.json # 技能原型人工校订结果（173 条，可复现）
│  ├─ aliases.csv              # 英雄别名词典（DataDragon + Hexdata）
│  ├─ hexdata_citation.json    # hexdata 引用溯源（buildId / reportPatch / reportDate）
│  ├─ augments.csv             # 强化符文表（海克斯池 223 条：中英文名/描述/稀有度/标签/图标）
│  ├─ augments_full.json       # 强化符文完整数据（程序加载用）
│  ├─ augment_pools.json       # 各模式启用池（CHERRY=57 / KIWI=223 / KIWI_JADE=188）
│  ├─ augment_display_tags.json# 强化符文类别标签文本（伤害/经济/速度… 11 类）
│  └─ snapshot.json            # 快照元信息（版本/数量/时间/来源）
├─ agg/                        # 聚合统计（hexdata 等）
│  ├─ LATEST                   # 指向当前 buildId 的指针
│  └─ <buildId>/               # 每次抓取一份
│     ├─ raw/                  # 原始 ai-summary.json [gitignore，大]
│     ├─ top_heroes.csv        # 热门英雄（winRate/pickRate/games/tier）
│     ├─ top_augments.csv      # 热门强化符文（globalHexScore/coverage）
│     ├─ hero_aliases.csv      # 英雄昵称（172 条）
│     ├─ methodology.json      # 口径（样本分档 / Wilson / 排序）
│     └─ citation.json         # 引用溯源（buildId/reportPatch/reportDate + 署名）
├─ personal/                   # 本人 WeGame / LCU 自采对局 [整目录 gitignore，仅留 README]
│  ├─ README.md                # 合规说明（仅本人 / 红线）
│  ├─ wegame_credential.json   # 本人凭证 [不入库]
│  └─ matches.jsonl            # 本人对局 NDJSON [不入库]
├─ sample/                     # 随仓小样本（演示/测试）
│  └─ wegame_matches.sample.jsonl  # 对局 schema 示例（非真实数据）
├─ summonerlens.duckdb         # 本地落库（三路数据汇聚）[gitignore，可重建]
└─ pipeline_meta.json          # 落库元信息（表/视图/行数/来源分层）
```

## 再生成

```bash
python python/etl/fetch_datadragon.py             # 抓最新版本
python python/etl/fetch_datadragon.py 16.19.1     # 抓指定版本
python python/etl/build_skill_archetypes.py       # 生成技能原型标注表
python python/etl/build_aliases.py                # 生成英雄别名词典
python python/etl/fetch_augments.py               # 抓强化符文（CommunityDragon，海克斯池）
python python/etl/build_item_modes.py             # 生成装备模式归属表（ARAM Mayhem 核验）
python python/etl/fetch_hexdata.py                # 抓 hexdata 聚合统计 -> data/agg/<buildId>/
python python/etl/fetch_hexdata.py --check        # 只校验引用四字段完整性
python python/etl/fetch_wegame.py --self-check    # WeGame 采集自检（仅本人闸门故障注入）
python python/etl/fetch_wegame.py                 # 采本人对局（需凭证，退出码 3=未配置）
python tools/check_version_changes.py             # 比较最近两个版本
python tools/verify_archetypes.py                 # 校验技能原型标注（--self-test 故障注入）
python tools/verify_items.py                      # 校验装备模式归属（--self-test 故障注入）

# —— 本地落库（需托管 venv，含 duckdb）——
VENV=C:/Users/Administrator/.workbuddy/binaries/python/envs/summonerlens/Scripts/python.exe
$VENV python/etl/build_duckdb.py                  # 三路数据 -> data/summonerlens.duckdb
$VENV tools/verify_pipeline.py 16.20.1            # 数据管道端到端验收（--self-test 故障注入）
```

## 传输说明（重要）

本机出网走代理，**Python 标准库证书链验证失败** → 抓取脚本**一律 curl 优先**（走系统/代理 CA）。详见 `.agent/memory/appendices/A09`。

## 当前快照

| 版本 | 英雄 | 装备 | 强化符文(海克斯) | 说明 |
|---|---|---|---|---|
| 16.20.1 | 173 | 870 | 223 | 最新；已生成 原型标注 + 别名词典 + 强化符文 + 装备模式归属（cdragon 16.20.8248524） |
| 16.19.1 | 173 | 870 | — | 对照快照，用于版本变更检测 |

**聚合统计（hexdata）**：`hexdata-2026-09-27-f9b948bc5ff0`（patch 16.19 / 2026-09-27）。

**本地落库**：`data/summonerlens.duckdb` —— 10 表 + 视图 `v_heroes`，共 2679 行；每表带 `_source/_confidence/_asof/_collected_at`。三路数据验收见 `tools/verify_pipeline.py`（50 断言）。详见 `.agent/memory/appendices/A13`。
