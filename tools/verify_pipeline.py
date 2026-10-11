# -*- coding: utf-8 -*-
"""M2 · 数据管道端到端验收（含故障注入自检）。

验收对象（三路数据 + 本地落库 + 跨版本）：
  1) 元数据：data/meta/<ver>/{champions,items,augments,skill_archetypes}.csv
  2) 聚合统计：data/agg/<buildId>/{top_heroes,top_augments,hero_aliases}.csv + citation.json
  3) 本人对局：data/personal/matches.jsonl（**依赖本人凭证，允许缺席**）
  4) 本地落库：data/summonerlens.duckdb
  5) 跨版本（M5）：agg_top_{heroes,augments}_history / meta_champion_changes / v_hero_trend

用法：
  <venv>/python tools/verify_pipeline.py [version]             # 正常校验
  <venv>/python tools/verify_pipeline.py [version] --self-test # 故障注入（应 FAIL，退出码 1）

设计纪律：断言必须能真的变红（见 kb/M01、M11）；空结果判 FAIL；缺依赖数据只报 pending 不静默通过。
"""
import csv
import json
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:  # noqa: BLE001
    print("[verify] 缺少 duckdb，请用托管 venv 运行：")
    print("  C:/Users/Administrator/.workbuddy/binaries/python/envs/summonerlens/Scripts/python.exe "
          "tools/verify_pipeline.py")
    raise SystemExit(2)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


FAILS = []
PASSES = []


def check(label: str, cond: bool) -> None:
    if cond:
        PASSES.append(label)
        print(f"  ✅ {label}")
    else:
        FAILS.append(label)
        print(f"  ❌ {label}")


def csv_rows(p: Path) -> int:
    with p.open(encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.reader(f)) - 1  # 去表头


def pick_version(root: Path, args) -> str:
    argv = [a for a in args if not a.startswith("-")]
    if argv:
        return argv[0]
    metas = [p.name for p in (root / "data" / "meta").iterdir() if p.is_dir()]

    def key(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return sorted(metas, key=key)[-1]


def main() -> None:
    root = project_root()
    args = sys.argv[1:]
    self_test = "--self-test" in args
    ver = pick_version(root, args)

    print(f"===== M2 数据管道验收（版本 {ver}）=====")

    # ---- 1) 元数据 ----
    print("[1] 元数据（Data Dragon / CommunityDragon）")
    meta = root / "data" / "meta" / ver
    expected = {"champions.csv": 173, "items.csv": 870, "augments.csv": 223,
                "skill_archetypes.csv": 173}
    for fname, n in expected.items():
        fp = meta / fname
        if not fp.exists():
            check(f"{fname} 存在", False)
            continue
        actual = csv_rows(fp)
        if self_test and fname == "champions.csv":
            # 故障注入：故意要求 9999 行 —— 必然失败
            check(f"[SELF-TEST] {fname} 行数 == 9999（应 FAIL）", actual == 9999)
        else:
            check(f"{fname} 行数 == {n}（实际 {actual}）", actual == n)

    # ---- 2) 聚合统计（hexdata）----
    print("[2] 聚合统计（hexdata，须带四字段溯源）")
    agg_root = root / "data" / "agg"
    latest = agg_root / "LATEST"
    check("data/agg/LATEST 存在", latest.exists())
    if latest.exists():
        bid = latest.read_text(encoding="utf-8").strip()
        agg = agg_root / bid
        cit_fp = agg / "citation.json"
        check("citation.json 存在", cit_fp.exists())
        if cit_fp.exists():
            c = json.loads(cit_fp.read_text(encoding="utf-8"))
            for k in ("buildId", "reportPatch", "reportDate", "source"):
                check(f"引用字段 {k} 非空", bool(c.get(k)))
            check("引用含 Hexdata 署名", "Hexdata" in (c.get("attribution_text") or ""))
            check("usage_policy: 训练/商用 disallowed",
                  (c.get("usage_policy") or {}).get("model_training") == "disallowed"
                  and (c.get("usage_policy") or {}).get("commercial") == "disallowed")
        for fname, n in {"top_heroes.csv": 12, "top_augments.csv": 12, "hero_aliases.csv": 172}.items():
            fp = agg / fname
            check(f"{fname} 行数 == {n}", fp.exists() and csv_rows(fp) == n)

    # ---- 3) 本人对局（允许缺席）----
    print("[3] 本人对局（WeGame / LCU，次级佐证；允许缺席）")
    matches = root / "data" / "personal" / "matches.jsonl"
    personal_present = matches.exists() and matches.stat().st_size > 5
    if personal_present:
        check("matches.jsonl 已采集", True)
    else:
        print("  ⚠️ PENDING：未采集本人对局（依赖本人凭证，属预期）——不计 FAIL")

    # ---- 4) 本地落库（DuckDB）----
    print("[4] 本地落库（DuckDB）")
    db = root / "data" / "summonerlens.duckdb"
    check("summonerlens.duckdb 存在", db.exists())
    if db.exists():
        con = duckdb.connect(str(db), read_only=True)
        need_tables = ["meta_champions", "meta_items", "meta_items_modes", "meta_augments",
                       "meta_skill_archetypes", "meta_aliases",
                       "agg_top_heroes", "agg_top_augments", "agg_hero_aliases", "agg_citation"]
        tabs = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
        for t in need_tables:
            check(f"表 {t} 存在", t in tabs)

        # 三列来源/可信度/时效必须存在且非空
        for t in [x for x in need_tables if x in tabs]:
            cols = {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_name='{t}'").fetchall()}
            has = all(c in cols for c in ("_source", "_confidence", "_asof"))
            check(f"{t} 含 _source/_confidence/_asof", has)
            if has:
                n_null = con.execute(
                    f"SELECT count(*) FROM {t} WHERE _source IS NULL OR _confidence IS NULL "
                    "OR _asof IS NULL").fetchone()[0]
                check(f"{t} 溯源列无空值", n_null == 0)

        # 视图
        check("视图 v_heroes 行数 == 173",
              con.execute("SELECT count(*) FROM v_heroes").fetchone()[0] == 173)

        # 聚合表挂钩
        check("agg_citation 署名含 Hexdata",
              "Hexdata" in (con.execute(
                  "SELECT attribution_text FROM agg_citation").fetchone() or [""])[0])

        # 本人对局表：文件存在则表必须存在且全为 secondary
        if personal_present:
            check("personal_matches 表存在", "personal_matches" in tabs)
            if "personal_matches" in tabs:
                bad = con.execute(
                    "SELECT count(*) FROM personal_matches WHERE _confidence <> 'secondary'"
                ).fetchone()[0]
                check("personal_matches 全为 secondary（次级佐证）", bad == 0)

        # 元数据一致性：表行数 == CSV 行数
        check("meta_champions 行数 == 173",
              con.execute("SELECT count(*) FROM meta_champions").fetchone()[0] == 173)
        check("meta_augments 行数 == 223",
              con.execute("SELECT count(*) FROM meta_augments").fetchone()[0] == 223)

        # ---- 5) 跨版本落库（M5）----
        print("[5] 跨版本落库（M5：history 表 + 改动表 + 趋势视图）")
        reg_fp = root / "data" / "versions.json"
        agg_n = meta_n = None
        if reg_fp.exists():
            reg = json.loads(reg_fp.read_text(encoding="utf-8"))
            agg_n = reg.get("counts", {}).get("agg")
            meta_n = reg.get("counts", {}).get("meta")
        check("versions.json 存在（版本注册表）", agg_n is not None and meta_n is not None)

        m5_tables = ["agg_top_heroes_history", "agg_top_augments_history", "meta_champion_changes"]
        for t in m5_tables:
            check(f"表 {t} 存在（M5）", t in tabs)
        for t in [x for x in m5_tables if x in tabs]:
            cols = {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_name='{t}'").fetchall()}
            has = all(c in cols for c in ("_source", "_confidence", "_asof", "_collected_at"))
            check(f"{t} 四列溯源齐全（含 _collected_at）", has)
            if has:
                n_null = con.execute(
                    f"SELECT count(*) FROM {t} WHERE _source IS NULL OR _confidence IS NULL "
                    "OR _asof IS NULL OR _collected_at IS NULL").fetchone()[0]
                check(f"{t} 溯源列无空值", n_null == 0)

        # history：行数 = 快照数 × 12（每份 agg 有 12 名英雄/12 个符文），且多 buildId 并存
        if agg_n and "agg_top_heroes_history" in tabs and "agg_top_augments_history" in tabs:
            for t in ("agg_top_heroes_history", "agg_top_augments_history"):
                n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                check(f"{t} 行数 == {agg_n}×12 = {agg_n*12}", n == agg_n * 12)
            nb = con.execute(
                "SELECT count(DISTINCT _build_id) FROM agg_top_heroes_history").fetchone()[0]
            check(f"agg_top_heroes_history 覆盖 {agg_n} 个 buildId", nb == agg_n)

        # 改动表：非空 + 含已知真实改动（Vayne/stats）。空表必须判 FAIL（承 kb M01）
        if "meta_champion_changes" in tabs:
            n = con.execute("SELECT count(*) FROM meta_champion_changes").fetchone()[0]
            if meta_n and meta_n >= 2:
                check(f"meta_champion_changes 非空（{meta_n} 版元数据应有改动）", n > 0)
                known = con.execute(
                    "SELECT count(*) FROM meta_champion_changes WHERE champion_id='Vayne' "
                    "AND change_type='changed' AND fields LIKE '%stats%'").fetchone()[0]
                check("meta_champion_changes 含已知改动 Vayne/stats", known >= 1)
            else:
                print("  ⚠️ PENDING：meta 快照 <2 份，跨版本改动无从产生（预期）——不计 FAIL")

        # 趋势视图：行数 = 快照数 × 12，版本维 = 快照数
        check("视图 v_hero_trend 存在", "v_hero_trend" in tabs)
        if "v_hero_trend" in tabs and agg_n:
            n = con.execute("SELECT count(*) FROM v_hero_trend").fetchone()[0]
            check(f"v_hero_trend 行数 == {agg_n}×12 = {agg_n*12}", n == agg_n * 12)
            nb = con.execute("SELECT count(DISTINCT build_id) FROM v_hero_trend").fetchone()[0]
            check(f"v_hero_trend 版本数 == {agg_n}", nb == agg_n)

        if self_test and "v_hero_trend" in tabs:
            # 故障注入：只改判据（要求 99999 行）→ 必然 FAIL，证明 M5 断言确实作用于真实查询
            check("[SELF-TEST] v_hero_trend 行数 == 99999（应 FAIL）",
                  con.execute("SELECT count(*) FROM v_hero_trend").fetchone()[0] == 99999)

        con.close()

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
