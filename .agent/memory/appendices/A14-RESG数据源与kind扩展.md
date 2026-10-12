# A14 · RESG 数据源接入 + Kind 白名单扩展

**创建日期**：2026-10-12
**关联 commit**：`9351179` + `8ffb8f1`
**前置阅读**：A02（数据源许可边界）、A07（数据源扩展与可信度分级）

---

## 1. RESG 端点契约（resg.top）

### 1.1 公开端点列表

| 端点 | 返回类型 | 说明 |
|------|---------|------|
| `/api/v1/versions.js` | ES module 数组 | 版本列表 `[{version, collectedAt}]` |
| `/api/v1/versions/<ver>/champions.js` | ES module 数组 | 英雄完整池 |
| `/api/v1/versions/<ver>/augments.js` | ES module 数组 | 海克斯（augment）完整池 |
| `/api/v1/versions/<ver>/items.*` | **404** | 装备维度端点不存在（已探 8 种变体） |

### 1.2 字段契约

**英雄**：`{id, name, title, alias, roles, ip, tm, wm, wr, tier}`

| 字段 | 类型 | 含义 |
|------|------|------|
| id | str | 英雄内部 ID |
| name | str | 中文名 |
| title | str | 称号 |
| alias | str | 别名列表 |
| roles | str[] | 角色（英文：fighter/mage/assassin 等） |
| tm | int | 总场次 |
| wm | int | 胜场 |
| wr | float | 胜率（应等于 wm/tm） |
| tier | str | T0-T4 分级 |

**海克斯（augment）**：`{id, name, description, tooltip, ip, tm, wm, wr, pr, tier, quality, topChampions}`

| 字段 | 类型 | 含义 |
|------|------|------|
| pr | float | PickRate 登场率 |
| quality | float | 海克斯强度分（RESG 独有） |
| topChampions | str[] | 适配英雄列表 |

### 1.3 规模基线

- 英雄：**173 条**（≥150 视为正常）
- 海克斯：**211 条**（≥180 视为正常）

### 1.4 ES module 剥离

RESG 返回的是 `export default [...]` 形式的 ES module。剥离用正则（推荐）：
```python
import re
content = re.sub(r'^export\s+default\s+', '', raw_text.strip(), flags=re.MULTILINE)
# 兼容 `export default [` 和 `export default\n[` 两种写法
```

### 1.5 装备端点缺口（如实记录）

已探 8 种端点变体：`items.js`、`item-stats.js`、`champion-items.js`、`items-by-champion.js`、`/items/`、`/item/`、`/item-stats/`、`champion-items-stats.js` → 全 404。
RESG SPA 内部可能有装备数据但未开放端点。
**现状**：前端 item tab 展示 A12 元数据装备列表（870 件），含模式归属标注；聚合胜率待数据源出现后接入。

---

## 2. Kind 白名单扩展

### 2.1 完整 Kind 白名单（build v1.0 起）

| Kind | 含义 | 来源 | 可信度 |
|------|------|------|--------|
| `real_aggregate` | hexdata 聚合（top12） | fetch_hexdata.py | secondary |
| `real_aggregate_resg` | RESG 完整聚合 | fetch_resg.py | aggregate_resg |
| `real_meta` | Data Dragon 元数据 | fetch_meta.py | authoritative |
| `real_metadata` | A12 装备元数据（items_modes） | meta 快照 | authoritative |
| `real_versioned` | M5 版本化维度 | meta + 历史 | authoritative |
| `real_derived` | 派生分析 | stats/* | derived |
| `synthetic_fixture` | 合成夹具（M3） | gen_fixture.py | synthetic_fixture |
| `unavailable` | 数据源缺口（空数据集） | — | — |

### 2.2 白名单位置（三处必须同步）

| 位置 | 文件 | 行号（2026-10-12） |
|------|------|-------------------|
| 数据束构建 | `build_viz_bundle.py` | 每次新增数据集时设置 prov.kind |
| Python 验收 | `verify_m4.py` L182-187 | kind 白名单元组 |
| Node 单测 | `test_m4_unit.js` L222 | kind 白名单数组 |

### 2.3 建议：集中定义（待办）

当前 kind 白名单分散在三处，改一处容易漏另外两处。建议未来集中到 `python/stats/constants.py`：
```python
VALID_KINDS = {
    "real_aggregate", "real_aggregate_resg", "real_meta", "real_metadata",
    "real_versioned", "real_derived", "synthetic_fixture", "unavailable",
}
```

---

## 3. DuckDB RESG 表

### 3.1 表结构

| 表 | 行数 | 说明 |
|----|------|------|
| `agg_resg_champions` | 173 | 英雄完整池 |
| `agg_resg_augments` | 211 | 海克斯完整池 |

### 3.2 强制溯源列

| 列 | 值 | 说明 |
|----|-----|------|
| `_source` | `RESG (aggregate, resg.top)` | 数据源标识 |
| `_confidence` | `aggregate_resg` | 可信度分级（A07） |
| `_asof` | `16.20`（RESG 版本） | 数据时效 |
| `_collected_at` | ISO 时间戳 | 抓取时间 |

### 3.3 加载方式

独立函数 `build_resg_tables(con, root)`，作为 `main()` 的第四路追加，**不修改既有三路重建逻辑**。
理由：RESG 抓取失败不影响既有三表；可单独增量更新。

---

## 4. 关键经验教训

### 4.1 参数遮蔽（Parameter Shadowing）

**坑**：`load_resg_rankings(root, hero_meta, aug_meta, ver)` 内部第一行 `ver = latest.read_text().strip()` 覆盖了函数参数 `ver`，导致 items_modes.csv 路径拼接用了 RESG 版本号（16.20）而非 meta 版本号（16.20.1）。

**修复**：内部临时变量改名为 `resg_ver`，函数参数 `ver` 保留给 items_modes.csv。

**规则**：函数签名参数在函数内**只读取不覆盖**。内部临时变量加前缀 `_` 或用不同名。

### 4.2 Kind 白名单同步

每新增一个 kind 值，必须同步检查 `verify_m4.py` + `test_m4_unit.js` + `build_viz_bundle.py` 三处。
未来考虑集中定义（见 2.3）。

### 4.3 故障注入退出码反转

`sys.exit(1 if not all_ok else 0)` 和 `sys.exit(0 if not all_ok else 1)` 肉眼难辨。
写完 self-test 必须立即跑一遍验证退出码逻辑。

### 4.4 数据缺口如实标注

RESG/hexdata 均无装备聚合端点时：
- **不做**：编造假数据（wr=0.5 等）
- **不做**：空数据集 + kind=unavailable 不展示任何内容
- **正确做法**：展示已有元数据 + 标注数据源缺口 + 顶部说明条

### 4.5 .gitignore glob 模式

`data/agg/*/raw/` 只匹配 `data/agg/` 开头的路径，**不匹配** `data/agg_resg/`。
新增 `data/agg_resg/*/raw/` 规则。类似命名（agg vs agg_resg、hexdata vs resg）要分别处理。

---

## 5. 待办 / 未来扩展

| 项 | 说明 | 优先级 |
|----|------|--------|
| RESG 跨版本趋势 | 当前只有 LATEST 指针，未纳入 `tools/sync_snapshots.py` 注册表 | 低 |
| Kind 集中定义 | `python/stats/constants.py` 加 `VALID_KINDS`，各脚本 import | 中 |
| items 聚合胜率 | 等 RESG 开放装备端点或 SPA 可爬后接入 | 等待 |
| verify_resg 扩 DuckDB 注入 | 当前 --self-test 只改文件层和数据束层，DuckDB 层可未来扩展 | 低 |
