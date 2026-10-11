# -*- coding: utf-8 -*-
"""M3 · 统计/建模内核单元测试（纯函数，含分辨力检查）。

用法：
  <python> tools/test_m3_unit.py              # 期望全部 PASS，退出码 0
  <python> tools/test_m3_unit.py --self-test  # 故障注入：断言必须变红，退出码 1

纪律（见 kb/M01、M02、M11）：断言必须能**真的变红**；本文件除等值断言外，还刻意断言
"朴素/错误实现会被本判据拒绝"（分辨力），以避免断言无论怎么实现都恒绿。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from stats import mmr, wilson          # noqa: E402
from model import slices, synergy      # noqa: E402

PASSES, FAILS = [], []


def check(label, cond):
    (PASSES if cond else FAILS).append(label)
    print(f"  {'✅' if cond else '❌'} {label}")


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def t_wilson():
    print("[wilson] 区间/下界/分档")
    lo, c, up = wilson.wilson_interval(500, 1000)
    check("wilson(500,1000) 下界≈0.469069", approx(lo, 0.469069, 1e-5))
    check("wilson(500,1000) 中心=0.5", approx(c, 0.5, 1e-9))
    check("wilson(500,1000) 上界≈0.530931", approx(up, 0.530931, 1e-5))
    check("下界(50,100)≈0.40383", approx(wilson.wilson_lower_bound(50, 100), 0.40383, 1e-5))
    check("下界 ≤ 中心 ≤ 上界", lo <= c <= up)
    # 分辨力：朴素胜率不是下界（n=100 时下界应显著低于 p=0.5）
    check("分辨力：下界 != 朴素胜率（差>0.05）", abs(wilson.wilson_lower_bound(50, 100) - 0.5) > 0.05)
    # 分档边界
    check("分档: n=0/249→low", wilson.sample_tier(0) == "low" and wilson.sample_tier(249) == "low")
    check("分档: n=250/999→medium", wilson.sample_tier(250) == "medium" and wilson.sample_tier(999) == "medium")
    check("分档: n=1000→high", wilson.sample_tier(1000) == "high")
    check("推荐级: 249→none 250→recommend 1000→strong",
          (wilson.recommendation_level(249), wilson.recommendation_level(250),
           wilson.recommendation_level(1000)) == ("none", "recommend", "strong"))
    # 异常路径（元组为 (n, wins)）
    for n, wins, why in [(0, 0, "n=0"), (2, 3, "wins>n")]:
        try:
            wilson.wilson_interval(wins, n)
            check(f"异常路径 {why} 未抛错", False)
        except ValueError:
            check(f"异常路径 {why} 已抛错", True)


def t_rank():
    print("[wilson] 排序与反霸榜")
    rows = [
        {"key": "TRAP", "games": 20, "wins": 17},
        {"key": "SOLID", "games": 800, "wins": 440},
        {"key": "ANCHOR", "games": 1500, "wins": 818},
    ]
    raw = wilson.rank_entities(rows, wilson.METHOD_RAW)
    check("raw 排序榜首 = TRAP（小样本高胜率）", raw[0]["key"] == "TRAP")
    off = wilson.rank_entities(rows, wilson.METHOD_TIER_THEN_WILSON)
    check("官方排序榜首 = ANCHOR（high 档）", off[0]["key"] == "ANCHOR")
    check("官方排序把 TRAP 压到末位", off[-1]["key"] == "TRAP")
    rep = wilson.anti_domination_report(rows)
    check("反霸榜：raw 榜首 tier=low", rep["raw_top_tier"] == "low")
    check("反霸榜：raw 榜首被降位（demoted）", rep["demoted"] is True)
    # 分辨力：若把 TRAP 样本抬到 high 档并保持高胜率，则它应当能霸榜（证明档位规则真的在起作用）
    big = [{"key": "TRAP", "games": 1200, "wins": 1020},
           {"key": "ANCHOR", "games": 1500, "wins": 818}]
    check("分辨力：高样本高胜率应霸榜（档位规则确实生效）",
          wilson.rank_entities(big, wilson.METHOD_TIER_THEN_WILSON)[0]["key"] == "TRAP")
    # winRate 反推 wins
    r = wilson.enrich([{"key": "x", "games": 1000, "winRate": 0.55}])[0]
    check("winRate 反推 wins=550", r["wins"] == 550)


def t_mmr():
    print("[mmr] ELO 公式与分层")
    check("期望得分 E(1500,1500)=0.5", approx(mmr.expected_score(1500, 1500), 0.5, 1e-12))
    check("更新 (1500,1500,win)=1516.0", mmr.update_mmr(1500, 1500, 1) == 1516.0)
    check("更新 (1500,1500,lose)=1484.0", mmr.update_mmr(1500, 1500, 0) == 1484.0)
    check("更新 (1500,1900,win)=1529.1（胜强者多拿分）", mmr.update_mmr(1500, 1900, 1) == 1529.1)
    check("更新 (1500,1100,win)=1502.9（胜弱者少拿分）", mmr.update_mmr(1500, 1100, 1) == 1502.9)
    check("单调性：胜强者得分 > 胜弱者得分",
          mmr.update_mmr(1500, 1900, 1) > mmr.update_mmr(1500, 1100, 1))
    # 分辨力：错误的"无脑 +32"实现会被拒绝
    check("分辨力：win 不是无脑 +32", mmr.update_mmr(1500, 1900, 1) != 1532.0)
    # 序列收敛：真实 1900 对 1500，长期应升到 1800+
    seq = [(1500, 1)] * 60
    check("序列估计收敛（真 1900 对 1500，60 局后 >1800）",
          mmr.estimate_series(1500, seq) > 1800)
    # 分层嵌套
    ranked = [(f"P{i}", 2000 - i * 10) for i in range(50)]
    strata, info = mmr.assign_strata(ranked)
    nested = all(("top20" in s) <= ("top40" in s) <= ("all" in s) for s in strata.values())
    check("分层嵌套 top20 ⊆ top40 ⊆ all", nested)
    check("k20=ceil(0.2*50)=10", info["k20"] == 10)
    check("k40=ceil(0.4*50)=20", info["k40"] == 20)
    check("thr20 >= thr40", info["thr20"] >= info["thr40"])
    check("strata_for_rating 与 assign_strata 一致",
          mmr.strata_for_rating(2000, info["thr20"], info["thr40"]) == ["all", "top40", "top20"])
    check("皮尔逊 =1（完全正相关）", approx(mmr.pearson_correlation([1, 2, 3], [2, 4, 6]), 1.0, 1e-12))
    check("皮尔逊 =-1（完全负相关）", approx(mmr.pearson_correlation([1, 2, 3], [3, 2, 1]), -1.0, 1e-12))
    # 异常路径
    try:
        mmr.update_mmr(1500, 1500, 7)
        check("异常路径 result=7 未抛错", False)
    except ValueError:
        check("异常路径 result=7 已抛错", True)


def t_synergy():
    print("[synergy] 组合统计与 lift")
    recs = []
    for i in range(10):
        recs.append({"champion_id": 1, "augments": [10], "items": [100], "win": i < 8})
    for i in range(10):
        recs.append({"champion_id": 1, "augments": [99], "items": [100], "win": i < 5})
    check("全局胜率 = 13/20", approx(synergy.global_win_rate(recs), 0.65, 1e-9))
    rows, meta = synergy.combo_stats(recs, ["champion_id", "augment_id"], min_games=5)
    d = {(r["champion_id"], r["augment_id"]): r for r in rows}
    check("(1,10) 胜率 0.8", approx(d[(1, 10)]["winRate"], 0.8, 1e-9))
    check("(1,10) 边际英雄胜率 0.65", approx(d[(1, 10)]["expected_hero_wr"], 0.65, 1e-9))
    check("(1,10) lift_vs_hero = +0.15", approx(d[(1, 10)]["lift_vs_hero"], 0.15, 1e-9))
    check("(1,99) lift_vs_hero = -0.15", approx(d[(1, 99)]["lift_vs_hero"], -0.15, 1e-9))
    check("组合按 Wilson 下界降序", rows[0]["wilson_lower"] >= rows[-1]["wilson_lower"])
    check("min_games 过滤生效（n<5 被剔除）", all(r["games"] >= 5 for r in rows))
    # 空数组字段不产出组合
    check("augments 为空 -> 无组合", list(synergy.iter_combo_keys(
        {"champion_id": 1, "augments": []}, ["champion_id", "augment_id"])) == [])
    # 三元组
    trows, _ = synergy.combo_stats(recs, ["champion_id", "augment_id", "item_id"], min_games=5)
    check("三元组行数=2", len(trows) == 2)


def t_slices():
    print("[slices] 分层切片")
    recs = [{"player_id": "A", "champion_id": 1, "augments": [10], "items": [1], "win": True},
            {"player_id": "B", "champion_id": 1, "augments": [10], "items": [1], "win": False},
            {"player_id": "C", "champion_id": 2, "augments": [10], "items": [1], "win": True}]
    strata = {"A": ["all", "top40", "top20"], "B": ["all", "top40"], "C": ["all"]}
    check("top20 切片只含 A", [r["player_id"] for r in slices.slice_records(recs, strata, "top20")] == ["A"])
    check("top40 切片含 A、B",
          sorted(r["player_id"] for r in slices.slice_records(recs, strata, "top40")) == ["A", "B"])
    check("all 切片含三人", len(slices.slice_records(recs, strata, "all")) == 3)
    rows, summary = slices.stats_by_stratum(recs, strata, "champion_id")
    check("切片统计含三档", set(summary) == {"top20", "top40", "all"})
    check("切片计数嵌套 all>=top40>=top20",
          summary["all"]["matches"] >= summary["top40"]["matches"] >= summary["top20"]["matches"])


def main():
    self_test = "--self-test" in sys.argv[1:]
    print("===== M3 单元测试 =====")
    t_wilson()
    t_rank()
    t_mmr()
    t_synergy()
    t_slices()
    if self_test:
        print("[self-test] 故障注入：断言应失败")
        check("[SELF-TEST] 故意断言 E(1500,1500)=0.9（应 FAIL）",
              approx(mmr.expected_score(1500, 1500), 0.9, 1e-9))
    print(f"\n通过 {len(PASSES)} / 失败 {len(FAILS)}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
