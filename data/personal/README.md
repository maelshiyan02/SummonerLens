# data/personal · 本人自采对局（隐私 · 不入库）

> 🔴 本目录**整个被 .gitignore 排除**（仅保留本 README）。
> 内容含**本人账号凭证**与**个人对局**，属于隐私数据，**绝不上传仓库、绝不同步网盘**。

## 放什么

| 文件 | 说明 | 是否入库 |
|---|---|---|
| `wegame_credential.json` | WeGame 本人凭证（self_id / area / token / cookie / endpoints） | ❌ 绝不 |
| `matches.jsonl` | 采集到的**本人**对局（NDJSON，每条一行） | ❌ 绝不 |

## 采集方式（合规：仅本人）

```bash
# 1) 准备凭证：环境变量或本地文件（见 python/etl/fetch_wegame.py 顶部说明）
# 2) 自检（含「仅本人」故障注入）
python python/etl/fetch_wegame.py --self-check
# 3) 干跑（只打印将请求的 URL，不发请求）
python python/etl/fetch_wegame.py --dry-run
# 4) 正式采集（本地运行，需本人凭证）
python python/etl/fetch_wegame.py
```

## LCU 本地客户端采集（推荐，无需 token / 抓包）

英雄联盟客户端运行时，本地 `127.0.0.1` 暴露 LCU API，可直接拉**本人**全部对局；
不需要任何 WeGame / 掌盟凭证，也不需要抓包，合规最稳、字段最全（A07 评「中高」）。

```bash
# 1) 逻辑自检（含故障注入：非本人对局不冒领）
python python/etl/fetch_lcu.py --self-check
# 2) 干跑（确认客户端已启动、lockfile 端口可读）
python python/etl/fetch_lcu.py --dry-run
# 3) 正式采集本人 ARAM 对局（默认 queue=450 / 限 20 条）
python python/etl/fetch_lcu.py
#   指定数量：python python/etl/fetch_lcu.py --queue 450 --limit 50
```

> 落库后 `matches.jsonl` 的 `source` 标 `lcu`、`confidence` 标 `primary`（高于 WeGame 的 `secondary`）；
> 与 WeGame 采集结果**共用同一文件、同一 `personal_matches` 表**，按 `source` 列区分。
> 客户端未运行时脚本会提示找不到 lockfile 并安全退出，不访问网络。

### 国服 / WeGame 现实说明

- 国服 LOL **经 WeGame 启动**，这不影响 LCU 采集：客户端进程由 WeGame 拉起的**仍是同一个
  LeagueClient**，运行时一样在盘上写 `lockfile`（`LeagueClient:<pid>:<port>:<password>:<protocol>`）。
  所以**通过 WeGame 正常启动客户端（进大厅即可，不必开局）**后就能采集，无需「绕过 WeGame」。
- 安装目录随用户/盘符/版本漂移（自定义盘、`WeGameApps`、中文目录名等），脚本因此：
  1. 先查固定候选；2. 未命中则**深度受限扫描 C:/D:/E:/F:**（跳过 `Windows`/`Users` 等系统顶层），
     按内容识别（首段必须是 `LeagueClient`）——不误判其他软件的 lockfile。
- 可用 `--lockfile <路径>` 手动指定、`--no-scan` 跳过扫描。
- 若沙盒/远端环境与客户端不在同一 loopback 命名空间，采集可能连不上 `127.0.0.1:<port>`；
  此时在**本机**跑同一条命令即可，产出同样落 `data/personal/matches.jsonl`（gitignore）。

## 数据模型（详细对局 schema v2 · LCU / WeGame 共用）

`matches.jsonl` 每条一行，是**完整对局**而非仅本人一行。统一结构如下（LCU 由
`fetch_lcu.parse_lcu_game` 产出，WeGame 的 `fetch_wegame.parse_battle` 须对齐同 shape）：

```jsonc
{
  "match_id": 12345, "game_creation": 1750000000, "game_duration": 1300,
  "queue_id": 450, "game_mode": "ARAM", "map_id": 12, "game_version": "16.20.1",
  "self_puuid": "<本人puuid>",          // 用于在 participants 中定位本人行
  "is_self": true,                       // 非本人对局为 false（不冒领）
  "source": "lcu", "confidence": "primary", "collected_at": "2026-10-12T...",
  "participants": [                       // 全部 10 名参与者（详细）
    {
      "puuid","summoner_name","champion_id","champion_name","team_id",
      "spell1_id","spell2_id","win",
      "kills","deaths","assists","champ_level","gold_earned",
      "damage_to_champions","magic_dmg_champ","physical_dmg_champ","true_dmg_champ",
      "damage_taken","damage_self_mitigated","total_heal",
      "vision_score","wards_placed","wards_killed",
      "total_minions_killed","neutral_minions_killed",        // CS = 小兵 + 野怪
      "items":[1,2,3,4,5,6],"trinket":3340,
      "primary_style":8000,"secondary_style":8300,"perks":[8112,8124,...],
      "augments":[10,20,30],                                  // ARAM 海克斯（3 槽）
      "double_kills","triple_kills","quadra_kills","penta_kills",
      "first_blood_kill","first_tower_kill"
    }
  ],
  "teams": [                             // 双方队伍目标
    {"team_id":100,"win":true,"tower_kills":3,"inhibitor_kills":0,
     "dragon_kills":2,"baron_kills":0,"rift_herald_kills":0,"nexus_kills":0}
  ],
  "raw_excerpt": "{}"                    // 截断原始响应，便于排障
}
```

下游消费：
- `python/etl/build_duckdb.py` → `personal_matches` 表（`read_json_auto` 自动摄入嵌套 participants/teams）。
- `python/bridge/build_viz_bundle.py → build_personal()` → `dashboard.json.personal`
  （summary / damage_breakdown 魔物真 / by_champion / recent 含 self 详情 + 双方队伍），
  前端「个人战绩」页渲染；**兼容旧扁平 schema**（无 participants 时按顶层字段兜底）。

## 红线

- **仅采集本人 / 已获授权账号**；脚本内置「仅本人」强校验（`assert_self`），非本人 id 一律拒绝。
- **不碰强制破解隐藏战绩**（注入 / 爬取他人隐私数据违反 ToS）。
- 局内**伤害 / 承伤**口径有偏 ⇒ 一律标注 `confidence = "secondary"`（次级佐证），仅参考。

回写记忆：`.agent/memory/appendices/A02`、`A07`、`A13`。
