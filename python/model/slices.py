# -*- coding: utf-8 -*-
"""M3 · 玩家分层切片（前20% / 前40% / 全量）。

给定「玩家 → 所属分层」映射，把对局切到某一层，再重算英雄/Augment 统计。
分层定义与嵌套保证见 python/stats/mmr.py（top20 ⊆ top40 ⊆ all）。
纯标准库；依赖 python/stats + python/model.synergy。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stats import wilson  # noqa: E402
from model.synergy import accumulate, global_win_rate  # noqa: E402

DEFAULT_STRATA = ("top20", "top40", "all")


def slice_records(records, strata_by_player, stratum, player_field="player_id"):
    """取属于某分层的对局子集。缺失玩家归属者计入 'all'。"""
    out = []
    for r in records:
        pid = r.get(player_field)
        layers = strata_by_player.get(pid)
        if layers is None:
            layers = ("all",)
        if stratum in layers:
            out.append(r)
    return out


def stats_by_stratum(records, strata_by_player, field, strata=DEFAULT_STRATA,
                     player_field="player_id", min_games=1):
    """按分层聚合某字段（如 champion_id）的胜率统计。

    返回 rows：stratum + fields 各列 + games/wins/winRate/wilson_*/sample_tier/
              global_winRate（该层内）
    """
    rows = []
    summary = {}
    for st in strata:
        sub = slice_records(records, strata_by_player, st, player_field)
        gwr = global_win_rate(sub)
        agg = accumulate(sub, [field])
        summary[st] = {"matches": len(sub), "global_winRate": gwr, "n_values": len(agg)}
        for combo, (g, w) in agg.items():
            if g < min_games:
                continue
            lb, center, ub = wilson.wilson_interval(w, g)
            rows.append({
                "stratum": st,
                field: combo[0],
                "games": g, "wins": w, "winRate": w / g,
                "wilson_lower": lb, "wilson_center": center, "wilson_upper": ub,
                "sample_tier": wilson.sample_tier(g),
                "global_winRate": gwr,
            })
    return rows, summary
