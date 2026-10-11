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

## 红线

- **仅采集本人 / 已获授权账号**；脚本内置「仅本人」强校验（`assert_self`），非本人 id 一律拒绝。
- **不碰强制破解隐藏战绩**（注入 / 爬取他人隐私数据违反 ToS）。
- 局内**伤害 / 承伤**口径有偏 ⇒ 一律标注 `confidence = "secondary"`（次级佐证），仅参考。

回写记忆：`.agent/memory/appendices/A02`、`A07`、`A13`。
