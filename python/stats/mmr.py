# -*- coding: utf-8 -*-
"""M3 · MMR/ELO 反推与玩家分层（前20% / 前40% / 全量）。

口径（见 A04 §3）：海克斯大乱斗有独立隐藏 MMR，Riot 不公开数值 ⇒ 本地对个人/语料
对局做 ELO 估计，再按分位分层，对接「玩家分段」切片维度。

纯标准库；模块无副作用。
"""
import math

DEFAULT_K = 32
DEFAULT_SCALE = 400.0
DEFAULT_INITIAL = 1500.0

# 分层：top20 = 前 20%，top40 = 前 40%，all = 全量（三者嵌套）
PCT_TOP20 = 0.20
PCT_TOP40 = 0.40
STRATA = ("top20", "top40", "all")


def expected_score(rating, opp_avg, scale=DEFAULT_SCALE):
    """ELO 期望得分（胜率期望）：E = 1 / (1 + 10^((opp_avg - rating)/scale))。"""
    return 1.0 / (1.0 + 10.0 ** ((float(opp_avg) - float(rating)) / float(scale)))


def update_mmr(rating, opp_avg, result, k=DEFAULT_K, scale=DEFAULT_SCALE):
    """单步 ELO 更新：new = rating + k * (result - expected)。result ∈ {1, 0, 0.5}。"""
    if result not in (0, 1, 0.5):
        raise ValueError(f"result 只能为 1/0/0.5，收到 {result}")
    exp = expected_score(rating, opp_avg, scale)
    return round(float(rating) + float(k) * (float(result) - exp), 1)


def estimate_series(initial=DEFAULT_INITIAL, sequence=(), k=DEFAULT_K, scale=DEFAULT_SCALE):
    """按时间顺序逐局更新，返回最终估计分。

    sequence: 可迭代的 (opp_avg, result) 序列。
    """
    rating = float(initial)
    for opp_avg, result in sequence:
        rating = update_mmr(rating, opp_avg, result, k, scale)
    return rating


def estimate_player(records, k=DEFAULT_K, scale=DEFAULT_SCALE, initial=DEFAULT_INITIAL):
    """从若干对局记录估计玩家分。

    record 需含：opp_avg_rating（对手均分）与 win（bool）。
    """
    seq = [(r["opp_avg_rating"], 1.0 if r.get("win") else 0.0) for r in records]
    return estimate_series(initial, seq, k, scale)


def assign_strata(ranked, pct_top20=PCT_TOP20, pct_top40=PCT_TOP40):
    """按分位给玩家分层，保证 top20 ⊆ top40 ⊆ all。

    ranked: [(player_id, rating), ...]，**须按 rating 降序**。
    返回 (strata_by_player, info)；info 含各组人数与分位门槛。
    """
    n = len(ranked)
    if n == 0:
        return {}, {"n": 0, "k20": 0, "k40": 0, "thr20": None, "thr40": None}
    k20 = max(1, int(math.ceil(pct_top20 * n)))
    k40 = max(1, int(math.ceil(pct_top40 * n)))
    out = {}
    for i, (pid, _rating) in enumerate(ranked, start=1):
        s = ["all"]
        if i <= k40:
            s.append("top40")
        if i <= k20:
            s.append("top20")
        out[pid] = s
    thr20 = ranked[k20 - 1][1]
    thr40 = ranked[k40 - 1][1]
    return out, {"n": n, "k20": k20, "k40": k40, "thr20": thr20, "thr40": thr40}


def strata_for_rating(rating, thr20, thr40):
    """流式判层：给定分与两门槛，返回该分所属分层列表（含 all）。thr20 >= thr40。"""
    s = ["all"]
    if thr40 is not None and rating >= thr40:
        s.append("top40")
    if thr20 is not None and rating >= thr20:
        s.append("top20")
    return s


def pearson_correlation(xs, ys):
    """皮尔逊相关系数（用于校验估计分与真实潜分的相关性）。"""
    n = len(xs)
    if n != len(ys) or n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)
