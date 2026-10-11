# -*- coding: utf-8 -*-
"""M5 · 收口验收（M5-1~M5-5 全链路 + 故障注入自检）。

验收对象：
  M5-1 版本注册表   data/versions.json（覆盖全部 meta/agg 快照，字段完整）
  M5-2 跨版本内核   python/stats/trend.py（meta diff 真实 / agg insufficient 契约）
  M5-3 落库 DuckDB  agg_top_{heroes,augments}_history / meta_champion_changes / v_hero_trend
  M5-4 前端标记     index.html（sel-ver / panel-version）+ app.js（溯源 render / synthetic 横幅）
  M5-5 自动化脚本   tools/sync_snapshots.py（存在 + 可编译 + self-test 通过）
  M5-6 本文件       tools/verify_m5.py（存在即为收口产物）

纪律（承 kb M01 / M11）：
  - 空结果判 FAIL：meta_champion_changes 在 ≥2 份 meta 下必须非空且含已知改动。
  - 快照不足不得冒充成功：agg 仅 1 份时 diff_agg 必须返回 insufficient_snapshots。
  - 每个「已完成」都要故障注入→断言真 FAIL；单测断言不得自洽。

用法：
  <venv>/python tools/verify_m5.py              # 正向全绿
  <venv>/python tools/verify_m5.py --self-test  # 故障注入，应 FAIL（退出码 1）
"""
import importlib.util
import json
import py_compile
import subprocess
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:  # noqa: BLE001
    print("[verify_m5] 缺少 duckdb，请用托管 venv 运行：")
    print("  C:/Users/Administrator/.workbuddy/binaries/python/envs/summonerlens/Scripts/python.exe "
          "tools/verify_m5.py")
    raise SystemExit(2)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


PASSES, FAILS = [], []


def check(label: str, cond: bool) -> None:
    if cond:
        PASSES.append(label)
        print(f"  ✅ {label}")
    else:
        FAILS.append(label)
        print(f"  ❌ {label}")


def load_trend():
    """加载 python/stats/trend.py 为模块（其 __file__ 决定 project_root）。"""
    spec = importlib.util.spec_from_file_location(
        "sl_trend", str(project_root() / "python" / "stats" / "trend.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    root = project_root()
    args = sys.argv[1:]
    self_test = "--self-test" in args

    print("===== M5 收口验收 =====")

    # ---------------------------------------------------------------- M5-1
    print("[M5-1] 版本注册表 data/versions.json")
    reg_fp = root / "data" / "versions.json"
    check("versions.json 存在", reg_fp.exists())
    reg = None
    if reg_fp.exists():
        reg = json.loads(reg_fp.read_text(encoding="utf-8"))
        check("schema == summonerlens.versions.v1", reg.get("schema") == "summonerlens.versions.v1")
        counts = reg.get("counts", {})
        check(f"meta 快照数 ≥ 2（实际 {counts.get('meta')}）", (counts.get("meta") or 0) >= 2)
        check(f"agg 快照数 ≥ 1（实际 {counts.get('agg')}）", (counts.get("agg") or 0) >= 1)
        snaps = reg.get("snapshots", [])
        check("snapshots 非空且含 kind 字段",
              snaps and all(s.get("kind") in ("meta", "agg") for s in snaps))
        check("注册表无 warnings", not reg.get("warnings"))
        if self_test:
            check("[SELF-TEST] counts.meta == 99（应 FAIL）", counts.get("meta") == 99)

    # ---------------------------------------------------------------- M5-2
    print("[M5-2] 跨版本内核 python/stats/trend.py")
    trend = load_trend()
    if reg_fp.exists():
        # 元数据真实 diff：16.19.1 -> 16.20.1 应检出 7 位英雄机制/数值改动
        res = trend.diff_meta(root, "16.19.1", "16.20.1")
        check("diff_meta 状态 ok", res.get("status") == "ok")
        n_changed = len(res.get("champions", {}).get("changed", []))
        check(f"16.19.1→16.20.1 英雄改动数 == 7（实际 {n_changed}）", n_changed == 7)
        vayne = next((c for c in res["champions"]["changed"] if c["id"] == "Vayne"), None)
        check("含已知改动 Vayne（且改动字段含 stats）",
              vayne is not None and "stats" in (vayne.get("fields") or []))
        if self_test:
            # 故障注入：断言 Vayne 不在改动列表（实际在）→ 必败，证明断言真作用于真实数据
            check("[SELF-TEST] Vayne 不在改动列表（应 FAIL）", vayne is None)

        # 聚合 diff 契约：agg 仅 1 份 → 必须返回 insufficient_snapshots
        agg_ids = [s["id"] for s in reg.get("snapshots", []) if s.get("kind") == "agg"]
        pair = trend.pick_latest_pair(root, "agg")
        check("agg 快照 < 2 → pick_latest_pair 返回 None（强制 insufficient 路径）", pair is None)
        # 直接验证契约：传入两个不存在的 id 也应返回 insufficient（不冒充成功）
        inc = trend.diff_agg(root, "no-such-A", "no-such-B")
        check("diff_agg 缺快照 → insufficient_snapshots（不冒充成功）",
              inc.get("status") == "insufficient_snapshots")
        if self_test:
            check("[SELF-TEST] diff_agg 单快照应返回 ok（应 FAIL）",
                  inc.get("status") == "ok")

    # ---------------------------------------------------------------- M5-3
    print("[M5-3] 落库 DuckDB（M5 表 + 四列溯源）")
    db = root / "data" / "summonerlens.duckdb"
    check("summonerlens.duckdb 存在", db.exists())
    if db.exists():
        con = duckdb.connect(str(db), read_only=True)
        tabs = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
        m5_tables = ["agg_top_heroes_history", "agg_top_augments_history", "meta_champion_changes"]
        for t in m5_tables:
            check(f"表 {t} 存在（M5）", t in tabs)
        for t in [x for x in m5_tables if x in tabs]:
            cols = {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_name='{t}'").fetchall()}
            has4 = all(c in cols for c in ("_source", "_confidence", "_asof", "_collected_at"))
            check(f"{t} 四列溯源齐全", has4)
            if has4:
                n_null = con.execute(
                    f"SELECT count(*) FROM {t} WHERE _source IS NULL OR _confidence IS NULL "
                    "OR _asof IS NULL OR _collected_at IS NULL").fetchone()[0]
                check(f"{t} 溯源列无空值", n_null == 0)

        agg_n = reg.get("counts", {}).get("agg") if reg else None
        if agg_n and "agg_top_heroes_history" in tabs:
            n = con.execute("SELECT count(*) FROM agg_top_heroes_history").fetchone()[0]
            check(f"agg_top_heroes_history 行数 == {agg_n}×12 = {agg_n*12}", n == agg_n * 12)
            if self_test:
                check("[SELF-TEST] agg_top_heroes_history 行数 == 99999（应 FAIL）", n == 99999)

        if "meta_champion_changes" in tabs:
            n = con.execute("SELECT count(*) FROM meta_champion_changes").fetchone()[0]
            meta_n = reg.get("counts", {}).get("meta") if reg else None
            if meta_n and meta_n >= 2:
                check(f"meta_champion_changes 非空（实际 {n} 行）", n > 0)
                known = con.execute(
                    "SELECT count(*) FROM meta_champion_changes WHERE champion_id='Vayne' "
                    "AND change_type='changed' AND fields LIKE '%stats%'").fetchone()[0]
                check("meta_champion_changes 含已知改动 Vayne/stats", known >= 1)
                if self_test:
                    check("[SELF-TEST] meta_champion_changes 行数 == 999（应 FAIL）", n == 999)
            else:
                print("  ⚠️ PENDING：meta 快照 <2 份，跨版本改动无从产生（预期）——不计 FAIL")

        check("视图 v_hero_trend 存在", "v_hero_trend" in tabs)
        if "v_hero_trend" in tabs and agg_n:
            n = con.execute("SELECT count(*) FROM v_hero_trend").fetchone()[0]
            check(f"v_hero_trend 行数 == {agg_n}×12 = {agg_n*12}", n == agg_n * 12)
            nb = con.execute("SELECT count(DISTINCT build_id) FROM v_hero_trend").fetchone()[0]
            check(f"v_hero_trend 版本数 == {agg_n}", nb == agg_n)
        con.close()

    # ---------------------------------------------------------------- M5-4
    print("[M5-4] 前端标记（版本选择器 / 版本变更视图 / 溯源角标 / synthetic 横幅）")
    html = root / "app" / "web" / "index.html"
    js = root / "app" / "web" / "js" / "app.js"
    if html.exists():
        h = html.read_text(encoding="utf-8")
        check('index.html 含版本选择器 id="sel-ver"', 'id="sel-ver"' in h)
        check('index.html 含版本变更视图 id="panel-version"', 'id="panel-version"' in h)
        if self_test:
            check('[SELF-TEST] index.html 不含 sel-ver（应 FAIL）', 'sel-ver' not in h)
    if js.exists():
        j = js.read_text(encoding="utf-8")
        check("app.js 含溯源 render（reportDate + buildId）",
              "reportDate" in j and "buildId" in j)
        check("app.js 含 synthetic/real 趋势分支（real_aggregate / synthetic_fixture）",
              "real_aggregate" in j and "synthetic_fixture" in j)

    # ---------------------------------------------------------------- M5-5
    print("[M5-5] 自动化脚本 tools/sync_snapshots.py")
    sync = root / "tools" / "sync_snapshots.py"
    check("sync_snapshots.py 存在", sync.exists())
    if sync.exists():
        try:
            py_compile.compile(str(sync), doraise=True)
            check("sync_snapshots.py 语法可编译", True)
        except py_compile.PyCompileError as e:
            check(f"sync_snapshots.py 语法可编译（{e}）", False)
        # self-test 无需网络，必须退出 0
        r = subprocess.run([sys.executable, str(sync), "--self-test"],
                           capture_output=True, text=True, encoding="utf-8")
        check("sync_snapshots.py --self-test 退出 0", r.returncode == 0)
        if r.returncode != 0:
            print("    " + r.stderr.strip().replace("\n", "\n    ")[-800:])

    # ---------------------------------------------------------------- M5-6
    print("[M5-6] 收口产物")
    check("verify_m5.py 存在（本文件）", Path(__file__).exists())

    # ---------------------------------------------------------------- 汇总
    print("\n===== 汇总 =====")
    print(f"  通过 {len(PASSES)} / 失败 {len(FAILS)}")
    if FAILS:
        print("  失败项：")
        for f in FAILS:
            print(f"    - {f}")
        sys.exit(1)
    tag = "（含 SELF-TEST 注入，均按预期 FAIL）" if self_test else ""
    print(f"  ✅ 全部通过 {tag}")
    sys.exit(0)


if __name__ == "__main__":
    main()
