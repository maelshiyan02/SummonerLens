# -*- coding: utf-8 -*-
"""M3 · Wilson 95% 下界 + 样本分档 + 排序（治小样本霸榜）。

口径（见 A04 / hexdata methodology.json）：
  - Wilson 95% 区间，z = 1.96
  - 样本分档：low n<250 | medium 250<=n<1000 | high n>=1000
  - 推荐等级：none n<250 | recommend n>=250 | strong n>=1000
  - 排序方法：
      * "raw_winrate"                           —— 直接按胜率（对照组，用于暴露"小样本霸榜"）
      * "wilson_lower_bound"                    —— 按 Wilson 下界
      * "sample_tier_then_wilson_lower_bound_v1" —— 先分档、档内按下界（hexdata 同款）

纯标准库；模块无副作用。
"""
import math

Z_95 = 1.96
TIER_LOW_MAX = 250          # n < 250 -> low
TIER_MEDIUM_MAX = 1000      # 250 <= n < 1000 -> medium ; n >= 1000 -> high

TIER_ORDER = {"low": 0, "medium": 1, "high": 2}
RECOMMEND_MIN = 250
RECOMMEND_STRONG = 1000

METHOD_RAW = "raw_winrate"
METHOD_WILSON = "wilson_lower_bound"
METHOD_TIER_THEN_WILSON = "sample_tier_then_wilson_lower_bound_v1"
METHODS = (METHOD_RAW, METHOD_WILSON, METHOD_TIER_THEN_WILSON)


def sample_tier(n):
    """样本分档：low / medium / high。"""
    n = int(n)
    if n < 0:
        raise ValueError(f"样本数不能为负：{n}")
    if n < TIER_LOW_MAX:
        return "low"
    if n < TIER_MEDIUM_MAX:
        return "medium"
    return "high"


def recommendation_level(n):
    """推荐等级：none(<250) / recommend(>=250) / strong(>=1000)。"""
    n = int(n)
    if n < RECOMMEND_MIN:
        return "none"
    if n < RECOMMEND_STRONG:
        return "recommend"
    return "strong"


def wilson_interval(wins, n, z=Z_95):
    """Wilson score 区间，返回 (lower, center, upper)。

    center = (p + z^2/2n) / (1 + z^2/n)
    margin = z * sqrt(p(1-p)/n + z^2/4n^2) / (1 + z^2/n)
    """
    n = int(n)
    wins = int(wins)
    if n <= 0:
        raise ValueError("wilson_interval 需要 n >= 1")
    if wins < 0 or wins > n:
        raise ValueError(f"wins({wins}) 必须在 [0, n({n})] 内")
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (lower, center, upper)


def wilson_lower_bound(wins, n, z=Z_95):
    """Wilson 95% 置信下界（排序主信号）。"""
    return wilson_interval(wins, n, z)[0]


def normalize_row(row):
    """把一行原始统计规范化为带 wins/games/winRate 的 dict（不修改入参）。

    允许输入里给 `winRate`（0~1）；缺 `wins` 时由 winRate*games 反推并取整。
    """
    games = row.get("games")
    if games is None:
        raise ValueError("统计行缺少 games")
    games = int(games)
    wins = row.get("wins")
    if wins is None:
        wr = row.get("winRate", row.get("win_rate"))
        if wr is None:
            raise ValueError("统计行需给 wins 或 winRate 之一")
        wins = int(round(float(wr) * games))
    wins = int(wins)
    return {"games": games, "wins": wins}


def enrich(rows, z=Z_95):
    """为每行补算 winRate（观测胜率 = wins/games） / Wilson 三值 / 样本档 / 推荐等级（不排序）。

    注意：`winRate` 是**观测胜率**；`wilson_center` 才是向 0.5 收缩后的平滑中心值。
    """
    out = []
    for r in rows:
        base = normalize_row(r)
        n, w = base["games"], base["wins"]
        lb, center, ub = wilson_interval(w, n, z)
        out.append({
            **r,
            "games": n,
            "wins": w,
            "winRate": w / n,
            "wilson_lower": lb,
            "wilson_center": center,
            "wilson_upper": ub,
            "sample_tier": sample_tier(n),
            "recommendation_level": recommendation_level(n),
        })
    return out


def _sort_key(method):
    if method == METHOD_RAW:
        return lambda r: (-r["winRate"], -r["games"])
    if method == METHOD_WILSON:
        return lambda r: (-r["wilson_lower"], -r["games"])
    if method == METHOD_TIER_THEN_WILSON:
        return lambda r: (
            -TIER_ORDER[r["sample_tier"]],
            -r["wilson_lower"],
            -float(r.get("pickRate", r.get("pick_rate", 0.0)) or 0.0),
            -r["games"],
        )
    raise ValueError(f"未知排序方法：{method}（可用：{METHODS}）")


def rank_entities(rows, method=METHOD_TIER_THEN_WILSON, z=Z_95):
    """排序并给 rank（1 起）。

    rows 需含 games，且含 wins 或 winRate。
    返回新列表，每行附加：rank / rank_method / wilson_* / sample_tier / recommendation_level。
    """
    if method not in METHODS:
        raise ValueError(f"未知排序方法：{method}（可用：{METHODS}）")
    enriched = enrich(rows, z)
    enriched.sort(key=_sort_key(method))
    for i, r in enumerate(enriched, start=1):
        r["rank"] = i
        r["rank_method"] = method
    return enriched


def anti_domination_report(rows, z=Z_95):
    """对比 raw 与 tier-then-wilson 两种排序，量化「小样本高胜率被下界压低」的效果。

    返回：
      {raw_top: <raw 排名第 1 的行标识>, wilson_top: <...>,
       raw_top_games: int, raw_top_tier: str,
       demoted: bool（raw 榜首在 wilson 排序里不再是第 1）,
       raw_top_wilson_rank: int}
    """
    raw = rank_entities(rows, METHOD_RAW, z)
    wil = rank_entities(rows, METHOD_TIER_THEN_WILSON, z)
    ident = lambda r: r.get("key", r.get("id", r.get("name")))
    raw_top = raw[0]
    wil_rank_of_raw_top = next(
        (r["rank"] for r in wil if ident(r) == ident(raw_top)), None)
    return {
        "raw_top": ident(raw_top),
        "wilson_top": ident(wil[0]),
        "raw_top_games": raw_top["games"],
        "raw_top_tier": raw_top["sample_tier"],
        "raw_top_wilson_rank": wil_rank_of_raw_top,
        "demoted": wil_rank_of_raw_top != 1,
    }
