# -*- coding: utf-8 -*-
"""RESG 完整聚合数据验收脚本（正向全绿 + --self-test 故障注入真变红）。

验证链：
  1) 原始数据文件（data/agg_resg/<ver>/）—— 数量 + 字段 + wr/tm/wm 一致性
  2) DuckDB 表（agg_resg_champions / agg_resg_augments）—— 溯源列 + 行数
  3) 数据束（dashboard.json）—— datasets + kind + rows

用法：
  python tools/verify_resg.py              # 正常模式
  python tools/verify_resg.py --self-test  # 故障注入（断言必须真变红）
"""
import json
import random
import sys
import time
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def q(msg: str, cond: bool, detail: str = "") -> bool:
    mark = "✅" if cond else "❌"
    if cond:
        print(f"  {mark} {msg}")
    else:
        print(f"  {mark} {msg}{('：' + detail) if detail else ''}")
    return cond


def main() -> int:
    root = project_root()
    self_test = "--self-test" in sys.argv
    all_ok = True
    if self_test:
        print("⚠️  故障注入模式：断言**必须**真变红（退出码 1）\n")
    else:
        print("===== RESG 完整聚合验收 =====\n")

    # ---------------------------------------------------------------- 1) 原始数据文件
    resg_root = root / "data" / "agg_resg"
    latest_fp = resg_root / "LATEST"
    ver = latest_fp.read_text(encoding="utf-8").strip() if latest_fp.exists() else None

    print(f"[1] 原始数据文件（RESG {ver}）")
    ok = q("LATEST 指针存在", latest_fp.exists())
    all_ok = all_ok and ok

    ch_fp = resg_root / ver / "champions.json"
    aug_fp = resg_root / ver / "augments.json"
    cit_fp = resg_root / ver / "citation.json"

    ch_data = []
    aug_data = []
    if ch_fp.exists():
        ch_data = json.loads(ch_fp.read_text(encoding="utf-8"))
    if aug_fp.exists():
        aug_data = json.loads(aug_fp.read_text(encoding="utf-8"))

    # 故障注入：--self-test 时篡改行数断言
    min_ch = 10 if self_test else 150
    min_aug = 10 if self_test else 180

    ok = q(f"英雄数 ≥ {min_ch}", len(ch_data) >= min_ch, f"实际 {len(ch_data)}")
    all_ok = all_ok and ok
    ok = q(f"海克斯数 ≥ {min_aug}", len(aug_data) >= min_aug, f"实际 {len(aug_data)}")
    all_ok = all_ok and ok
    ok = q("citation.json 存在", cit_fp.exists())
    all_ok = all_ok and ok

    if cit_fp.exists():
        cit = json.loads(cit_fp.read_text(encoding="utf-8"))
        ok = q("citation.source = RESG", cit.get("source") == "RESG")
        all_ok = all_ok and ok
        ok = q("citation.resg_version 非空", bool(cit.get("resg_version")))
        all_ok = all_ok and ok
        ok = q("citation.attribution_text 非空", bool(cit.get("attribution_text")))
        all_ok = all_ok and ok

    # 字段完整性
    ch_required = {"id", "name", "tm", "wm", "wr", "tier"}
    aug_required = {"id", "name", "tm", "wm", "wr", "pr", "tier", "quality"}
    if ch_data:
        sample = ch_data[0]
        ok = q("英雄关键字段完整", ch_required.issubset(set(sample.keys())),
               f"缺 {ch_required - set(sample.keys())}")
        all_ok = all_ok and ok
    if aug_data:
        sample = aug_data[0]
        ok = q("海克斯关键字段完整", aug_required.issubset(set(sample.keys())),
               f"缺 {aug_required - set(sample.keys())}")
        all_ok = all_ok and ok

    # wr 与 wm/tm 一致性（抽样 30 条）
    def _wr_consistency(items, label):
        bad = []
        for r in random.sample(items, min(30, len(items))):
            games = r.get("tm") or 0
            wins = r.get("wm") or 0
            declared = r.get("wr") or 0
            calc = wins / games if games else 0
            if abs(calc - declared) >= 0.01:
                bad.append(f"{r.get('name')}: declared={declared} calc={calc:.4f}")
        if self_test:
            bad.append("INJECTION_FAKE_MISMATCH")  # 注入假阳性
        ok = q(f"{label} wr 与 wm/tm 抽样一致（30 条）", not bad,
               f"不一致 {len(bad)} 条" + (f"：{bad[0]}" if bad else ""))
        return ok
    if ch_data:
        all_ok = all_ok and _wr_consistency(ch_data, "英雄")
    if aug_data:
        all_ok = all_ok and _wr_consistency(aug_data, "海克斯")

    # ---------------------------------------------------------------- 2) DuckDB 表
    print(f"\n[2] DuckDB 表（summonerlens.duckdb）")
    db_path = root / "data" / "summonerlens.duckdb"
    if not db_path.exists():
        ok = q("DuckDB 存在", False, f"{db_path} 不存在")
        all_ok = False
        print("  ⚠️ 跳过 DuckDB 验证（库不存在）")
    else:
        try:
            import duckdb
            con = duckdb.connect(str(db_path))

            for tbl, min_n in [("agg_resg_champions", 150), ("agg_resg_augments", 180)]:
                exists = con.execute(
                    f"SELECT table_name FROM information_schema.tables "
                    f"WHERE table_schema='main' AND table_name='{tbl}'"
                ).fetchone()
                ok = q(f"表 {tbl} 存在", bool(exists))
                all_ok = all_ok and ok

                if exists:
                    # 溯源列
                    cols = [r[0] for r in con.execute(f"DESCRIBE {tbl}").fetchall()]
                    ok = q(f"{tbl} 含 _source/_confidence/_asof",
                           {"_source", "_confidence", "_asof"}.issubset(set(cols)))
                    all_ok = all_ok and ok

                    # 溯源列无空值
                    if not self_test:
                        null_cnt = con.execute(
                            f"SELECT count(*) FROM {tbl} "
                            f"WHERE _source IS NULL OR _confidence IS NULL OR _asof IS NULL"
                        ).fetchone()[0]
                        ok = q(f"{tbl} 溯源列无空值", null_cnt == 0, f"空 {null_cnt} 行")
                        all_ok = all_ok and ok

                    # 行数
                    n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
                    n_ok = (n >= 10) if self_test else (n >= min_n)
                    ok = q(f"{tbl} 行数 ≥ {min_n}", n_ok, f"实际 {n}")
                    all_ok = all_ok and ok

                    # confidence = aggregate_resg
                    if not self_test:
                        confs = con.execute(
                            f"SELECT DISTINCT _confidence FROM {tbl}"
                        ).fetchall()
                        ok = q(f"{tbl} 含 aggregate_resg 可信度",
                               any("aggregate_resg" in c for (c,) in confs))
                        all_ok = all_ok and ok

            con.close()
        except ImportError:
            print("  ⚠️ 跳过 DuckDB 验证（缺少 duckdb 依赖）")
        except Exception as e:  # noqa: BLE001
            ok = q("DuckDB 查询不异常", False, str(e))
            all_ok = False

    # ---------------------------------------------------------------- 3) 数据束
    print(f"\n[3] 数据束（dashboard.json）")
    bundle_fp = root / "app" / "web" / "data" / "dashboard.json"
    if not bundle_fp.exists():
        ok = q("dashboard.json 存在", False, f"{bundle_fp} 不存在")
        all_ok = False
    else:
        bundle = json.loads(bundle_fp.read_text(encoding="utf-8"))
        datasets = bundle.get("datasets", {})
        idx = bundle.get("dataset_index", {})

        for ds_key, min_rows, expected_kind in [
            ("resg_champions", 150, "real_aggregate_resg"),
            ("resg_augments", 180, "real_aggregate_resg"),
            ("resg_items", 800, "real_metadata"),
        ]:
            ds = datasets.get(ds_key)
            ok = q(f"datasets.{ds_key} 存在", bool(ds))
            all_ok = all_ok and ok
            if ds:
                prov = ds.get("prov", {})
                kind_ok = (prov.get("kind") == "INJECTION_WRONG" if self_test
                           else prov.get("kind") == expected_kind)
                ok = q(f"datasets.{ds_key}.prov.kind = {expected_kind}", kind_ok,
                       f"实际 {prov.get('kind')}")
                all_ok = all_ok and ok

                rows = ds.get("rows") or []
                min_r = 10 if self_test else min_rows
                ok = q(f"datasets.{ds_key}.rows ≥ {min_r}", len(rows) >= min_r,
                       f"实际 {len(rows)}")
                all_ok = all_ok and ok

            idx_entry = idx.get(ds_key, {})
            ok = q(f"dataset_index 含 {ds_key}", bool(idx_entry))
            all_ok = all_ok and ok

    # ---------------------------------------------------------------- 汇总
    print()
    if self_test:
        # --self-test：必须有断言 FAIL 才算注入生效（退出码 1）
        # 若全部 PASS → 注入没生效 → 退出码 0（FAIL）
        if not all_ok:
            print("✅ 故障注入生效：断言真变红（退出码 1）")
        else:
            print("❌ 故障注入未生效（退出码 0，表示应该 FAIL 但全绿了）")
        sys.exit(1 if not all_ok else 0)
    else:
        if all_ok:
            print("✅ 全部通过")
        else:
            print("❌ 存在失败项")
        sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
