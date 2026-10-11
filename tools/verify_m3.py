# -*- coding: utf-8 -*-
"""M3 · 统计与建模内核端到端验收（含故障注入自检）。

验收对象：data/derived/m3/<corpus>/ 下的全部派生表（由 python/model/run_m3.py 生成）。
默认校验 synthetic 语料（引擎校验夹具）；若本人对局已采集，可另跑 --corpus=personal。

用法：
  <python> tools/verify_m3.py                 # 正常验收（缺产物会先自动生成）
  <python> tools/verify_m3.py --self-test     # 故障注入：断言必须变红，退出码 1
  <python> tools/verify_m3.py --corpus=personal

纪律（见 kb/M01/M02/M11）：
  - 断言必须能**真的变红**；空结果判 FAIL。
  - 故障注入**只换输入**（篡改已解析的 bundle），与正常校验**共用同一套判据**。
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from stats import mmr, wilson  # noqa: E402

PASSES, FAILS = [], []
EXPECTED_OUTPUTS = [
    "corpus_hero_stats.csv", "corpus_augment_stats.csv", "corpus_item_stats.csv",
    "corpus_hero_augment_pairs.csv", "corpus_hero_item_pairs.csv",
    "corpus_hero_augment_item_triples.csv", "corpus_player_mmr.csv",
    "corpus_slices_hero_stats.csv", "hexdata_hero_ranking.csv", "hexdata_augment_ranking.csv",
]
STATS_FILES = ["corpus_hero_stats.csv", "corpus_augment_stats.csv", "corpus_item_stats.csv",
               "corpus_hero_augment_pairs.csv", "corpus_hero_item_pairs.csv",
               "corpus_hero_augment_item_triples.csv", "corpus_slices_hero_stats.csv",
               "hexdata_hero_ranking.csv", "hexdata_augment_ranking.csv"]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def check(label, cond):
    (PASSES if cond else FAILS).append(label)
    print(f"  {'✅' if cond else '❌'} {label}")


def safe(label, fn):
    """执行判据；异常一律判 FAIL（故障注入不应把脚本炸掉）。"""
    try:
        check(label, bool(fn()))
    except Exception as e:  # noqa: BLE001
        check(f"{label}（异常：{type(e).__name__}: {e}）", False)


def to_num(v):
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s == "":
        return s
    if s in ("True", "False"):
        return s == "True"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return v


def read_csv(p: Path):
    with p.open(encoding="utf-8-sig", newline="") as f:
        return [{k: to_num(v) for k, v in row.items()} for row in csv.DictReader(f)]


def ensure_outputs(root: Path, corpus: str):
    outdir = root / "data" / "derived" / "m3" / corpus
    if not (outdir / "stats_meta.json").exists():
        print(f"[verify] 缺产物，先运行 run_m3（corpus={corpus}）...")
        subprocess.run([sys.executable, str(root / "python" / "model" / "run_m3.py"),
                        f"--corpus={corpus}"], check=True)
    return outdir


def load_bundle(root: Path, corpus: str):
    outdir = ensure_outputs(root, corpus)
    b = {"outdir": outdir, "corpus": corpus}
    b["meta"] = json.loads((outdir / "stats_meta.json").read_text(encoding="utf-8"))
    for name in EXPECTED_OUTPUTS:
        p = outdir / name
        b[name] = read_csv(p) if p.exists() else None
    mf = root / "data" / "sample" / "m3_corpus.synth.manifest.json"
    b["manifest"] = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    return b


# ---------------- 判据 ----------------

def c_meta(b):
    print("[1] 元数据与方法论")
    m = b["meta"].get("methodology", {})
    safe("wilson_z == 1.96", lambda: m.get("wilson_z") == 1.96)
    safe("排序方法 = sample_tier_then_wilson_lower_bound_v1",
         lambda: m.get("ranking") == "sample_tier_then_wilson_lower_bound_v1")
    safe("样本分档口径 = low<250 / 250-999 / high>=1000",
         lambda: m.get("sample_tiers") == {"low": "<250", "medium": "250-999", "high": ">=1000"})
    safe("corpus.kind 已登记", lambda: bool(b["meta"].get("corpus", {}).get("kind")))


def c_files(b):
    print("[2] 产物齐全且非空（空结果判 FAIL）")
    for name in EXPECTED_OUTPUTS:
        rows = b.get(name)
        safe(f"{name} 存在", lambda: rows is not None)
        safe(f"{name} 非空（{0 if rows is None else len(rows)} 行）",
             lambda: rows is not None and len(rows) >= 1)


def c_wilson_consistency(b):
    print("[3] Wilson 一致性（下界 ≤ 观测胜率 ≤ 上界；三值与 wins/games 重算一致）")
    for name in STATS_FILES:
        rows = b.get(name) or []
        bad_order = bad_match = 0
        for r in rows:
            lb, c, ub = r["wilson_lower"], r["wilson_center"], r["wilson_upper"]
            obs = r["winRate"]
            if not (lb <= obs <= ub + 1e-9):
                bad_order += 1
            rl, rc, ru = wilson.wilson_interval(int(r["wins"]), int(r["games"]))
            if abs(rl - lb) > 1e-6 or abs(rc - c) > 1e-6 or abs(ru - ub) > 1e-6:
                bad_match += 1
        safe(f"{name}: 区间包含观测胜率", lambda: bad_order == 0)
        safe(f"{name}: Wilson 三值可由 wins/games 重算", lambda: bad_match == 0)


def c_tier_consistency(b):
    print("[4] 样本分档一致性（tier 与 games 重算一致）")
    for name in STATS_FILES:
        rows = b.get(name) or []
        bad = sum(1 for r in rows if r["sample_tier"] != wilson.sample_tier(int(r["games"])))
        safe(f"{name}: sample_tier 与 games 匹配", lambda: bad == 0)


def c_ranking(b):
    print("[5] 排序正确性")
    rows = b.get("corpus_hero_stats.csv") or []
    safe("英雄排名 rank 连续 1..N", lambda: sorted(int(r["rank"]) for r in rows) == list(range(1, len(rows) + 1)))
    order = {"low": 0, "medium": 1, "high": 2}
    seq = [order[r["sample_tier"]] for r in sorted(rows, key=lambda r: int(r["rank"]))]
    safe("官方排序下 档位等级非递增", lambda: all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1)))
    safe("官方排序 rank1 = high 档",
         lambda: sorted(rows, key=lambda r: int(r["rank"]))[0]["sample_tier"] == "high")


def c_anti_domination(b):
    print("[6] 反霸榜（小样本高胜率不霸榜）")
    anti = b["meta"].get("anti_domination", {})
    safe("raw 胜率榜首为 low 档（小样本）", lambda: anti.get("raw_top_tier") == "low")
    safe("raw 榜首被官方方法降位（demoted）", lambda: anti.get("demoted") is True)
    rows = b.get("corpus_hero_stats.csv") or []
    raw_top_key = anti.get("raw_top")
    if rows and raw_top_key is not None:
        raw_row = next((r for r in rows if r["key"] == raw_top_key), None)
        safe("raw 榜首存在且 games<250", lambda: raw_row is not None and int(raw_row["games"]) < 250)
        safe("raw 榜首官方排名 > 1", lambda: raw_row is not None and int(raw_row["rank"]) > 1)


def c_synergy(b):
    print("[7] 协同计算（英雄 × Augment × 装备）")
    man = b.get("manifest", {})
    strong, weak = man.get("strong_combo"), man.get("weak_combo")
    specs = [
        ("corpus_hero_augment_pairs.csv", [("champion_id", "hero"), ("augment_id", "augment")]),
        ("corpus_hero_item_pairs.csv", [("champion_id", "hero"), ("item_id", "item")]),
        ("corpus_hero_augment_item_triples.csv",
         [("champion_id", "hero"), ("augment_id", "augment"), ("item_id", "item")]),
    ]
    for fname, mapping in specs:
        rows = b.get(fname) or []
        if not strong:
            continue

        def find(cb):
            return next((r for r in rows
                         if all(r[rk] == cb[ck] for rk, ck in mapping)), None)
        s, w = find(strong), find(weak)
        safe(f"{fname}: 命中植入强协同行", lambda: s is not None)
        safe(f"{fname}: 强协同 lift_vs_hero > +0.08", lambda: s is not None and s["lift_vs_hero"] > 0.08)
        safe(f"{fname}: 弱协同 lift_vs_hero < -0.05", lambda: w is not None and w["lift_vs_hero"] < -0.05)
        safe(f"{fname}: 组合均满足最小样本门槛(>=60)",
             lambda: all(int(r["games"]) >= 60 for r in rows))
        safe(f"{fname}: 按 Wilson 下界降序",
             lambda: all(rows[i]["wilson_lower"] >= rows[i + 1]["wilson_lower"]
                         for i in range(len(rows) - 1)))


def c_mmr(b):
    print("[8] MMR/ELO 反推与分层")
    safe("ELO 公式：update(1500,1500,win)=1516.0", lambda: mmr.update_mmr(1500, 1500, 1) == 1516.0)
    safe("ELO 公式：update(1500,1900,win)=1529.1", lambda: mmr.update_mmr(1500, 1900, 1) == 1529.1)
    rows = b.get("corpus_player_mmr.csv") or []
    safe("分层：in_top20 ⇒ in_top40", lambda: all(
        (not r["in_top20"]) or r["in_top40"] for r in rows))
    n = len(rows)
    k20 = sum(1 for r in rows if r["in_top20"])
    k40 = sum(1 for r in rows if r["in_top40"])
    import math
    safe(f"top20 人数 = ceil(0.2N)={math.ceil(0.2 * n)}", lambda: k20 == math.ceil(0.2 * n))
    safe(f"top40 人数 = ceil(0.4N)={math.ceil(0.4 * n)}", lambda: k40 == math.ceil(0.4 * n))
    safe("玩家分降序排列",
         lambda: all(rows[i]["estimated_mmr"] >= rows[i + 1]["estimated_mmr"]
                     for i in range(len(rows) - 1)))
    if b["corpus"] == "synthetic":
        corr = b["meta"].get("corpus", {}).get("mmr_recovery_corr")
        safe(f"MMR 反推与潜分相关 > 0.5（实际 {corr}）", lambda: corr is not None and corr > 0.5)


def c_slices(b):
    print("[9] 分层切片")
    sm = b["meta"].get("slice_summary", {})
    safe("切片含 top20/top40/all 三档", lambda: set(sm) >= {"top20", "top40", "all"})
    safe("切片对局数嵌套 all>=top40>=top20", lambda:
         sm.get("all", {}).get("matches", 0) >= sm.get("top40", {}).get("matches", 0)
         >= sm.get("top20", {}).get("matches", 0))
    rows = b.get("corpus_slices_hero_stats.csv") or []
    safe("切片表含三档 stratum", lambda: {r["stratum"] for r in rows} >= {"top20", "top40", "all"})


def c_provenance(b):
    print("[10] 溯源与合成标注（A07 硬要求）")
    for name in EXPECTED_OUTPUTS:
        rows = b.get(name) or []
        bad = sum(1 for r in rows
                  if not (r.get("_source") and r.get("_confidence")
                          and r.get("_asof") and r.get("_collected_at")))
        safe(f"{name}: 溯源四列非空", lambda: bad == 0)
    if b["corpus"] == "synthetic":
        corpus_files = [n for n in EXPECTED_OUTPUTS if n.startswith("corpus_")]
        for name in corpus_files:
            rows = b.get(name) or []
            safe(f"{name}: 合成标注 _confidence=fixture",
                 lambda: all(r.get("_confidence") == "fixture" for r in rows))
            safe(f"{name}: 合成标注 _corpus=synthetic_fixture",
                 lambda: all(r.get("_corpus") == "synthetic_fixture" for r in rows))


def c_hexdata(b):
    print("[11] hexdata 真实聚合数据排名与引用")
    for name, n in [("hexdata_hero_ranking.csv", 12), ("hexdata_augment_ranking.csv", 12)]:
        rows = b.get(name) or []
        safe(f"{name} 行数 == {n}", lambda: len(rows) == n)
        safe(f"{name} 行引用含 Hexdata",
             lambda: all("Hexdata" in str(r.get("_citation", "")) for r in rows))
        safe(f"{name} 全为 high 档（百万级样本）",
             lambda: all(r["sample_tier"] == "high" for r in rows))
    cit = b["meta"].get("hexdata_citation", {})
    for k in ("buildId", "reportPatch", "reportDate", "attribution_text"):
        safe(f"hexdata 引用字段 {k} 非空", lambda: bool(cit.get(k)))


def run_checks(b):
    PASSES.clear()
    FAILS.clear()
    c_meta(b)
    c_files(b)
    c_wilson_consistency(b)
    c_tier_consistency(b)
    c_ranking(b)
    c_anti_domination(b)
    c_synergy(b)
    c_mmr(b)
    c_slices(b)
    c_provenance(b)
    c_hexdata(b)


def inject_fault(b):
    """故障注入：只改输入（已解析 bundle），破坏 rank1 英雄的 Wilson 值与档位、
    并篡改反霸榜结论 —— 与正常校验共用同一套判据。"""
    rows = b.get("corpus_hero_stats.csv") or []
    r1 = next((r for r in rows if int(r.get("rank", 0)) == 1), None)
    if r1 is not None:
        r1["wilson_lower"] = 0.999        # 与 wins/games 不一致 -> 触发 [3]
        r1["sample_tier"] = "low"         # 与 games 不一致       -> 触发 [4]/[5]
    b["meta"].setdefault("anti_domination", {})["demoted"] = False  # -> 触发 [6]
    return b


def main():
    root = project_root()
    args = sys.argv[1:]
    self_test = "--self-test" in args
    corpus = next((a.split("=", 1)[1] for a in args if a.startswith("--corpus=")), "synthetic")

    print(f"===== M3 统计与建模内核验收（corpus={corpus}）=====")
    b = load_bundle(root, corpus)
    if self_test:
        print("[self-test] 故障注入已生效（篡改输入，共用判据）")
        inject_fault(b)
    run_checks(b)

    print("\n===== 汇总 =====")
    print(f"  通过 {len(PASSES)} / 失败 {len(FAILS)}")
    if FAILS:
        print("  失败项：")
        for f in FAILS:
            print(f"    - {f}")
        sys.exit(1)
    print("  ✅ 全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
