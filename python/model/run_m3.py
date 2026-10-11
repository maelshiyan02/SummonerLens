# -*- coding: utf-8 -*-
"""M3 · 统计与建模内核编排（跑通 Wilson / 协同 / MMR / 分层切片）。

输入语料：
  - synthetic（默认，无本人对局时）：data/sample/m3_corpus.synth.jsonl（由 gen_fixture.py 生成）
  - personal ：data/personal/matches.jsonl（本人 WeGame/LCU 自采，次级佐证；存在时优先）

输出（全部为派生，.gitignore 排除）：data/derived/m3/<corpus_kind>/
  corpus_hero_stats.csv           英雄：games/wins/winRate/Wilson/档/推荐级/官方排名
  corpus_augment_stats.csv        Augment 同上
  corpus_item_stats.csv           装备 同上
  corpus_hero_augment_pairs.csv   英雄 × Augment：+ lift_vs_hero / lift_vs_global
  corpus_hero_item_pairs.csv      英雄 × 装备：同上
  corpus_hero_augment_item_triples.csv  英雄 × Augment × 装备：同上
  corpus_player_mmr.csv           玩家：估计分 + 分层（top20/top40/all）
  corpus_slices_hero_stats.csv    按分层切片的英雄统计
  hexdata_hero_ranking.csv        hexdata 前 12 英雄的 Wilson 排名（真实聚合数据）
  hexdata_augment_ranking.csv     hexdata 前 12 Augment 的 Wilson 排名
  stats_meta.json                 方法论 + 溯源 + 清单

纪律：项目根由脚本自身位置推导；只用标准库 + 本项目 python/ 模块；
     每行输出带 `_source/_confidence/_asof/_collected_at`（A07 硬要求）。
"""
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stats import mmr, wilson            # noqa: E402
from model import slices, synergy        # noqa: E402

COMBINED_PAIR_MIN = 60      # 组合最小样本门槛（低于此不出组合结论，避免小样本噪声）
TRIPLE_MIN = 60
M3_METHOD = wilson.METHOD_TIER_THEN_WILSON


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def pick_version(root: Path) -> str:
    metas = [p.name for p in (root / "data" / "meta").iterdir() if p.is_dir()]

    def k(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return sorted(metas, key=k)[-1]


def load_jsonl(p: Path):
    out = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_csv(path: Path, rows, extra: dict):
    """写 CSV：行内键序 + extra(溯源列) 追加在末尾。空表也写表头。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    for k in extra:
        if k not in fields:
            fields.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, **extra})


def corpus_provenance(kind: str, ver: str):
    if kind == "personal":
        return {"_source": "WeGame / LCU (self, authorized)", "_confidence": "secondary",
                "_asof": ver, "_corpus": "personal_wegame"}
    return {"_source": "synthetic fixture (engine validation only)",
            "_confidence": "fixture", "_asof": ver, "_corpus": "synthetic_fixture"}


def stats_rows(records, field, label_key, min_games=1):
    """某字段的胜率统计 + 官方排序。"""
    agg = synergy.accumulate(records, [field])
    rows = []
    for combo, (g, w) in agg.items():
        if g < min_games:
            continue
        rows.append({"key": combo[0], "games": g, "wins": w, "pickRate": g / max(1, len(records))})
    return wilson.rank_entities(rows, M3_METHOD)


def resolve_corpus(root: Path, args):
    personal = root / "data" / "personal" / "matches.jsonl"
    want = next((a.split("=", 1)[1] for a in args if a.startswith("--corpus=")), None)
    if want in ("synthetic", "personal"):
        pass
    else:
        want = "personal" if (personal.exists() and personal.stat().st_size > 5) else "synthetic"
    if want == "personal":
        if not (personal.exists() and personal.stat().st_size > 5):
            print("[m3] ⚠️ 无本人对局数据（data/personal/matches.jsonl）—— 回退 synthetic。")
            want = "synthetic"
        else:
            return "personal", personal
    # synthetic：按需生成
    jl = root / "data" / "sample" / "m3_corpus.synth.jsonl"
    if not jl.exists():
        print("[m3] 生成合成夹具 ...")
        import model.gen_fixture as gf  # noqa: PLC0415
        gf.main()
    return "synthetic", jl


def main() -> None:
    root = project_root()
    args = sys.argv[1:]
    ver = next((a.split("=", 1)[1] for a in args if a.startswith("--ver=")), None) \
        or pick_version(root)

    kind, corpus_path = resolve_corpus(root, args)
    records = load_jsonl(corpus_path)
    if not records:
        print(f"[m3] ❌ 语料为空：{corpus_path} —— 空结果判 FAIL。")
        raise SystemExit(1)

    outdir = root / "data" / "derived" / "m3" / kind
    outdir.mkdir(parents=True, exist_ok=True)
    prov = corpus_provenance(kind, ver)
    prov["_collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"[m3] 语料 = {kind}（{len(records)} 局）| 版本 {ver}")

    # ---- 1) 单实体统计（英雄 / Augment / 装备）+ 官方排序 ----
    hero_rows = stats_rows(records, "champion_id", "champion_id")
    aug_rows = stats_rows(records, "augment_id", "augment_id")
    item_rows = stats_rows(records, "item_id", "item_id")
    write_csv(outdir / "corpus_hero_stats.csv", hero_rows, prov)
    write_csv(outdir / "corpus_augment_stats.csv", aug_rows, prov)
    write_csv(outdir / "corpus_item_stats.csv", item_rows, prov)

    # ---- 2) 协同：英雄 × Augment × 装备 ----
    pairs_ha, _ = synergy.combo_stats(records, ["champion_id", "augment_id"], COMBINED_PAIR_MIN)
    pairs_hi, _ = synergy.combo_stats(records, ["champion_id", "item_id"], COMBINED_PAIR_MIN)
    triples, _ = synergy.combo_stats(records, ["champion_id", "augment_id", "item_id"], TRIPLE_MIN)
    write_csv(outdir / "corpus_hero_augment_pairs.csv", pairs_ha, prov)
    write_csv(outdir / "corpus_hero_item_pairs.csv", pairs_hi, prov)
    write_csv(outdir / "corpus_hero_augment_item_triples.csv", triples, prov)

    # ---- 3) MMR 反推 + 玩家分层 ----
    by_player = {}
    for r in records:
        by_player.setdefault(r.get("player_id", "unknown"), []).append(r)
    mmr_rows = []
    for pid, rs in by_player.items():
        est = mmr.estimate_player(rs) if all("opp_avg_rating" in x for x in rs) \
            else mmr.estimate_series(mmr.DEFAULT_INITIAL, [])
        mmr_rows.append({"player_id": pid, "matches": len(rs), "estimated_mmr": est})
    ranked = sorted(((r["player_id"], r["estimated_mmr"]) for r in mmr_rows),
                    key=lambda t: (-t[1], t[0]))
    strata_by_player, strata_info = mmr.assign_strata(ranked)
    for r in mmr_rows:
        layers = strata_by_player.get(r["player_id"], ["all"])
        r["in_top20"] = "top20" in layers
        r["in_top40"] = "top40" in layers
    mmr_rows.sort(key=lambda r: -r["estimated_mmr"])
    write_csv(outdir / "corpus_player_mmr.csv", mmr_rows, prov)

    # ---- 4) 分层切片（英雄统计按 top20 / top40 / all）----
    slice_rows, slice_summary = slices.stats_by_stratum(
        records, strata_by_player, "champion_id", player_field="player_id")
    write_csv(outdir / "corpus_slices_hero_stats.csv", slice_rows, prov)

    # ---- 5) hexdata 真实聚合数据的 Wilson 排名（12 英雄 / 12 Augment）----
    hex_rows = {}
    agg_root = root / "data" / "agg"
    latest = agg_root / "LATEST"
    hex_citation = None
    if latest.exists():
        bid = latest.read_text(encoding="utf-8").strip()
        agg_dir = agg_root / bid
        cit_fp = agg_dir / "citation.json"
        if cit_fp.exists():
            hex_citation = json.loads(cit_fp.read_text(encoding="utf-8"))
        patch = (hex_citation or {}).get("reportPatch", ver)
        hex_prov = {
            "_source": "Hexdata (self-collected samples)", "_confidence": "aggregate_hexdata",
            "_asof": patch, "_build_id": bid,
            "_collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "_citation": (hex_citation or {}).get("attribution_text", ""),
        }
        for fname, outname, keycol in [
                ("top_heroes.csv", "hexdata_hero_ranking.csv", "id"),
                ("top_augments.csv", "hexdata_augment_ranking.csv", "id")]:
            fp = agg_dir / fname
            if not fp.exists():
                continue
            src = list(csv.DictReader(fp.open(encoding="utf-8-sig")))
            rows = [{"key": int(r[keycol]), "name": r.get("name"),
                     "games": int(float(r["games"])),
                     "winRate": float(r["winRate"]),
                     "pickRate": float(r.get("pickRate") or 0),
                     "wins": int(round(float(r["winRate"]) * float(r["games"])))} for r in src]
            ranked_rows = wilson.rank_entities(rows, M3_METHOD)
            write_csv(outdir / outname, ranked_rows, hex_prov)
            hex_rows[outname] = len(ranked_rows)

    # ---- 6) 元数据 ----
    anti = wilson.anti_domination_report([
        {"key": r["key"], "games": r["games"], "wins": r["wins"]} for r in hero_rows])

    corpus_meta = {"kind": kind, "path": str(corpus_path.relative_to(root)).replace("\\", "/"),
                   "n_records": len(records), "n_players": len(by_player)}
    if kind == "synthetic":
        mf = root / "data" / "sample" / "m3_corpus.synth.manifest.json"
        if mf.exists():
            man = json.loads(mf.read_text(encoding="utf-8"))
            corpus_meta["seed"] = man.get("seed")
            corpus_meta["planted"] = {
                "anchor_hero": man.get("anchor_hero"), "solid_hero": man.get("solid_hero"),
                "trap_hero": man.get("trap_hero"), "strong_combo": man.get("strong_combo"),
                "weak_combo": man.get("weak_combo")}
            est = {p: mmr.estimate_player(rs) for p, rs in by_player.items()
                   if p in man.get("player_skills", {})}
            truth = man.get("player_skills", {})
            if est:
                corpus_meta["mmr_recovery_corr"] = round(mmr.pearson_correlation(
                    [truth[p] for p in est], [est[p] for p in est]), 4)

    meta = {
        "milestone": "M3", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta_version": ver,
        "methodology": {
            "wilson_z": wilson.Z_95,
            "sample_tiers": {"low": "<250", "medium": "250-999", "high": ">=1000"},
            "recommendation": {"recommend": ">=250", "strong": ">=1000"},
            "ranking": M3_METHOD,
            "lift_definition": "lift_vs_hero = 组合胜率 - 该英雄边际胜率；lift_vs_global = 组合胜率 - 全局胜率",
            "combination_min_games": {"pair": COMBINED_PAIR_MIN, "triple": TRIPLE_MIN},
            "mmr": {"k": mmr.DEFAULT_K, "scale": mmr.DEFAULT_SCALE, "initial": mmr.DEFAULT_INITIAL},
            "strata": {"top20": "前20%", "top40": "前40%", "all": "全量", **strata_info},
        },
        "corpus": corpus_meta,
        "anti_domination": anti,
        "slice_summary": slice_summary,
        "outputs": {
            "corpus_hero_stats.csv": len(hero_rows),
            "corpus_augment_stats.csv": len(aug_rows),
            "corpus_item_stats.csv": len(item_rows),
            "corpus_hero_augment_pairs.csv": len(pairs_ha),
            "corpus_hero_item_pairs.csv": len(pairs_hi),
            "corpus_hero_augment_item_triples.csv": len(triples),
            "corpus_player_mmr.csv": len(mmr_rows),
            "corpus_slices_hero_stats.csv": len(slice_rows),
            **hex_rows,
        },
        "hexdata_citation": {
            "required_context": (hex_citation or {}).get("required_context"),
            "buildId": (hex_citation or {}).get("buildId"),
            "reportPatch": (hex_citation or {}).get("reportPatch"),
            "reportDate": (hex_citation or {}).get("reportDate"),
            "attribution_text": (hex_citation or {}).get("attribution_text"),
        },
        "notes": [
            "本产物为派生分析，可由 python/model/run_m3.py 重建。",
            "synthetic 语料仅用于引擎校验，绝非真实数据，勿用于对外结论。",
            "协同 lift 为关联而非因果；需满足最小样本门槛。",
        ],
    }
    (outdir / "stats_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[m3] 输出目录 = {outdir}")
    for k, v in meta["outputs"].items():
        print(f"   {k:38s} {v} 行")
    print(f"[m3] 反霸榜：raw 榜首 tier={anti['raw_top_tier']}（n={anti['raw_top_games']}）"
          f"→ 官方方法排第 {anti['raw_top_wilson_rank']}，demoted={anti['demoted']}")
    print(f"[m3] ✅ 完成")


if __name__ == "__main__":
    main()
