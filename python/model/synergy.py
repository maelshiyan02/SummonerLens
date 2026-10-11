# -*- coding: utf-8 -*-
"""M3 · 英雄 × Augment × 装备 胜率协同计算。

输入：对局级记录（每条含 champion_id、augments[]、items[]、win）。
输出：各组合的 games/wins/winRate + Wilson 下界 + 样本档 + 协同增益 lift。

协同增益（lift）定义：
  lift_vs_hero   = 组合胜率 − 该英雄的边际胜率     （"带了这个 Augment/装备，比英雄本身多赢多少"）
  lift_vs_global = 组合胜率 − 语料全局胜率

说明：lift 是**关联**而非因果（见 A02/A07 口径）；且需满足最小样本门槛才输出。
纯标准库；依赖 python/stats。
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stats import wilson  # noqa: E402

# 字段 -> 数据来源（scalar 取记录字段；list 从记录的数组字段展开）
FIELD_SOURCE = {
    "champion_id": ("scalar", "champion_id"),
    "augment_id": ("list", "augments"),
    "item_id": ("list", "items"),
}


def _options(rec, field):
    """取出某字段在该对局中的全部取值（标量单值；数组多值）。"""
    if field not in FIELD_SOURCE:
        raise ValueError(f"未知字段：{field}（可用：{list(FIELD_SOURCE)}）")
    kind, key = FIELD_SOURCE[field]
    if kind == "scalar":
        v = rec.get(key)
        return [] if v is None else [v]
    return list(rec.get(key) or [])


def iter_combo_keys(rec, fields):
    """对一条对局，展开出所有组合 key（笛卡尔积）；任一字段为空则该局不产出组合。"""
    opts = [_options(rec, f) for f in fields]
    if any(len(o) == 0 for o in opts):
        return
    for combo in itertools.product(*opts):
        yield combo


def accumulate(records, fields):
    """聚合：{combo_tuple: (games, wins)}。"""
    agg = {}
    for rec in records:
        win = 1 if rec.get("win") else 0
        for combo in iter_combo_keys(rec, fields):
            g, w = agg.get(combo, (0, 0))
            agg[combo] = (g + 1, w + win)
    return agg


def marginal_stats(records, field):
    """某字段各取值的边际 (winRate, games)。"""
    agg = {}
    for rec in records:
        win = 1 if rec.get("win") else 0
        for v in _options(rec, field):
            g, w = agg.get(v, (0, 0))
            agg[v] = (g + 1, w + win)
    return {v: (w / g, g) for v, (g, w) in agg.items() if g > 0}


def global_win_rate(records):
    n = len(records)
    if n == 0:
        return None
    return sum(1 for r in records if r.get("win")) / n


def combo_stats(records, fields, min_games=1):
    """组合统计。返回 (rows, meta)。

    rows 每行：fields 各列 + games/wins/winRate/wilson_*/sample_tier/
              expected_hero_wr/lift_vs_hero/lift_vs_global
    """
    gwr = global_win_rate(records)
    if gwr is None:
        return [], {"global_winRate": None, "n_rows": 0, "n_considered": 0}
    hero_marginal = marginal_stats(records, "champion_id") if "champion_id" in fields else {}
    agg = accumulate(records, fields)
    rows = []
    for combo, (g, w) in agg.items():
        if g < min_games:
            continue
        lb, center, ub = wilson.wilson_interval(w, g)
        obs = w / g                      # 观测胜率
        row = dict(zip(fields, combo))
        row.update({
            "games": g, "wins": w, "winRate": obs,
            "wilson_lower": lb, "wilson_center": center, "wilson_upper": ub,
            "sample_tier": wilson.sample_tier(g),
            "recommendation_level": wilson.recommendation_level(g),
            "global_winRate": gwr,
            "lift_vs_global": obs - gwr,
        })
        if "champion_id" in fields:
            hwr = hero_marginal.get(combo[fields.index("champion_id")], (None, 0))[0]
            row["expected_hero_wr"] = hwr
            row["lift_vs_hero"] = (obs - hwr) if hwr is not None else None
        rows.append(row)
    rows.sort(key=lambda r: (-r["wilson_lower"], -r["games"]))
    return rows, {"global_winRate": gwr, "n_rows": len(rows), "n_considered": len(agg)}


def rank_pairs(records, fields, min_games=1):
    """按 Wilson 下界排序的组合（前 N 由调用方截取）。"""
    rows, meta = combo_stats(records, fields, min_games)
    return rows, meta
