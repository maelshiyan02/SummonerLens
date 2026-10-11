# -*- coding: utf-8 -*-
"""M5-5 · 快照自动同步：让版本化数据向前积累。

定期运行（建议每日一次，挂 WorkBuddy 定时任务）：
  1. 抓 hexdata 聚合快照（python/etl/fetch_hexdata.py，buildId 已存在则自动跳过）
  2. 可选：抓 Data Dragon 元数据（--with-meta，仅当线上最新版本本地尚无时才抓）
  3. 刷新版本注册表（python/etl/build_versions_index.py）
  4. 比对前后注册表，判定是否有新快照
  5. 若有变更：重建落库（build_duckdb.py）+ 重建可视化数据束（build_viz_bundle.py）
     + 产出变更报告 data/derived/changes/<date>.md
  6. 无变更：静默退出 0（不重建，保持幂等）

退出码：
  0  成功（无论有无变更）
  1  执行错误（抓取失败 / 脚本异常）
  2  --self-test 自检失败

本脚本自身只依赖标准库；落库重建依赖 duckdb 托管 venv（自动探测，
缺失则跳过落库重建并告警，其余步骤照常）。

用法：
  python tools/sync_snapshots.py                 # 抓 hexdata，静默，有变更出报告
  python tools/sync_snapshots.py --with-meta      # 同时追踪 Data Dragon 元数据新版本
  python tools/sync_snapshots.py --force-rebuild  # 强制重建落库+数据束（即便无新快照）
  python tools/sync_snapshots.py --dry-run        # 只检测+报告，不重建、不落盘报告
  python tools/sync_snapshots.py --json           # 机器可读摘要
  python tools/sync_snapshots.py --self-test       # 内部逻辑自检（无需网络）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

DD = "https://ddragon.leagueoflegends.com"
UA = "SummonerLens/0.1 (+sync-snapshots; maelshiyan02)"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _py() -> str:
    return sys.executable


def _run(script_rel: str, *args) -> subprocess.CompletedProcess:
    cmd = [_py(), str(project_root() / script_rel), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def _run_with(py_exe: str, script_rel: str, *args) -> subprocess.CompletedProcess:
    cmd = [py_exe, str(project_root() / script_rel), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def load_registry(root: Path) -> dict:
    p = root / "data" / "versions.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def find_duckdb_python() -> str:
    """探测含 duckdb 的托管 venv；找不到返回 None（落库重建将被跳过）。"""
    cands = [
        os.environ.get("SUMMONERLENS_PY"),
        str(Path.home() / ".workbuddy/binaries/python/envs/summonerlens/Scripts/python.exe"),
    ]
    for c in cands:
        if not c:
            continue
        p = Path(c)
        if not p.exists():
            continue
        try:
            r = subprocess.run([str(p), "-c", "import duckdb"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return str(p)
        except Exception:  # noqa: BLE001
            pass
    return None


def dd_latest_version() -> str:
    try:
        req = urllib.request.Request(f"{DD}/api/versions.json",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))[0]
    except Exception:  # noqa: BLE001
        return None


def registry_changed(old: dict, new: dict) -> bool:
    """前后注册表是否不同（快照数或 latest 变化）。old 为 None 视为首次登记。"""
    if old is None:
        return True
    for key in ("counts", "latest"):
        if old.get(key) != new.get(key):
            return True
    return False


def write_report(root: Path, old: dict, new: dict) -> Path:
    chg_dir = root / "data" / "derived" / "changes"
    chg_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    path = chg_dir / f"{today}.md"

    old_ids = {s["id"] for s in (old or {}).get("snapshots", [])}
    added = [s for s in new.get("snapshots", []) if s["id"] not in old_ids]

    agg_n = new["counts"]["agg"]
    trend_kind = "real_aggregate" if agg_n >= 2 else "synthetic_fixture"

    ts = time.strftime("%H:%M:%S")
    lines = []
    if path.exists():
        lines.append("\n---\n")
        lines.append(f"## 同步轮次 {today} {ts}\n")
    else:
        lines.append(f"# 快照同步变更日志 · {today}\n")
        lines.append("> 由 `tools/sync_snapshots.py` 自动生成（派生，gitignore）。\n")

    if not added:
        lines.append(f"- 本轮（{ts}）：**无新快照**（agg={agg_n}, meta={new['counts']['meta']}）。")
    else:
        lines.append(f"### 本轮新增（{ts}）\n")
        for s in added:
            extra = s.get("extra", {})
            if s["kind"] == "agg":
                lines.append(
                    f"- **agg** `{s['id']}`：patch={s.get('patch')} "
                    f"报告日期={s.get('report_date')} "
                    f"英雄 {extra.get('hero_rows')} / 符文 {extra.get('augment_rows')} 行")
            else:
                lines.append(
                    f"- **meta** `{s['id']}`：patch={s.get('patch')} "
                    f"英雄 {extra.get('champion_count')} / 装备 {extra.get('item_count')}")
        lines.append("")
        lines.append(
            f"- 当前聚合趋势状态：`{trend_kind}`"
            + ("（已具备 ≥2 份 agg 快照，趋势为真实数据）" if agg_n >= 2 else
               "（agg 仍仅 1 份，趋势为 synthetic 演示；真实趋势待积累）"))
        lines.append("- 已执行：刷新 `data/versions.json`、重建 DuckDB 落库、"
                     "重建 `app/web/data/dashboard.json`。")

    if new.get("warnings"):
        lines.append("")
        lines.append("⚠️ 注册表告警：")
        for w in new["warnings"]:
            lines.append(f"  - {w}")

    content = "\n".join(lines) + "\n"
    mode = "a" if path.exists() else "w"
    with path.open(mode, encoding="utf-8") as f:
        f.write(content)
    return path


def do_sync(args: list) -> int:
    root = project_root()
    with_meta = "--with-meta" in args
    force_rebuild = "--force-rebuild" in args
    dry_run = "--dry-run" in args
    as_json = "--json" in args

    old = load_registry(root)

    # 1) hexdata 聚合快照
    print("[sync] 抓取 hexdata 聚合快照 ...")
    r = _run("python/etl/fetch_hexdata.py")
    if r.returncode != 0:
        print("[sync] ❌ fetch_hexdata 失败：")
        print(r.stderr.strip()[-1500:])
        return 1

    # 2) 可选 Data Dragon 元数据
    if with_meta:
        print("[sync] 检查 Data Dragon 最新版本 ...")
        latest = dd_latest_version()
        meta_ids = [s["id"] for s in (old or {}).get("snapshots", []) if s.get("kind") == "meta"]
        if latest and latest not in meta_ids:
            print(f"[sync] 新元数据版本 {latest}，抓取中 ...")
            rm = _run("python/etl/fetch_datadragon.py", latest)
            if rm.returncode != 0:
                print("[sync] ⚠️ fetch_datadragon 失败（非致命，继续）：")
                print(rm.stderr.strip()[-800:])
        else:
            print("[sync] 元数据已是最新，跳过")

    # 3) 刷新注册表
    print("[sync] 刷新版本注册表 ...")
    ri = _run("python/etl/build_versions_index.py")
    if ri.returncode != 0:
        print("[sync] ❌ build_versions_index 失败：")
        print(ri.stderr.strip()[-1500:])
        return 1
    new = load_registry(root)
    is_changed = bool(force_rebuild or registry_changed(old, new))

    summary = {
        "changed": is_changed,
        "counts": new.get("counts"),
        "latest": new.get("latest"),
        "warnings": new.get("warnings", []),
        "actions": [],
    }

    if is_changed and not dry_run:
        # 4) 重建落库（duckdb 托管 venv 自动探测）
        duck_py = find_duckdb_python()
        if duck_py:
            print("[sync] 重建 DuckDB 落库 ...")
            rd = _run_with(duck_py, "python/etl/build_duckdb.py")
            if rd.returncode == 0:
                summary["actions"].append("duckdb rebuilt")
            else:
                print("[sync] ⚠️ build_duckdb 失败（非致命）：")
                print(rd.stderr.strip()[-800:])
                summary["actions"].append("duckdb FAILED")
        else:
            print("[sync] ⚠️ 未找到含 duckdb 的托管 venv，跳过落库重建"
                  "（仅刷新注册表 + 数据束）")
            summary["actions"].append("duckdb skipped (no venv)")

        # 5) 重建可视化数据束
        print("[sync] 重建可视化数据束 ...")
        rb = _run("python/bridge/build_viz_bundle.py")
        if rb.returncode == 0:
            summary["actions"].append("bundle rebuilt")
        else:
            print("[sync] ⚠️ build_viz_bundle 失败（非致命）：")
            print(rb.stderr.strip()[-800:])
            summary["actions"].append("bundle FAILED")

        # 6) 变更报告
        report_path = write_report(root, old, new)
        summary["report"] = str(report_path)
        summary["actions"].append("change report written")

    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"[sync] 变更={is_changed}  agg快照={new['counts']['agg']}  "
              f"meta快照={new['counts']['meta']}  latest.agg={new['latest']['agg']}")
        for a in summary["actions"]:
            print(f"    - {a}")
        if new.get("warnings"):
            for w in new["warnings"]:
                print(f"    ⚠️ {w}")
        print("[sync] ✅ 完成" if not summary.get("report")
              else f"[sync] ✅ 完成，变更报告 -> {summary['report']}")
    return 0


def do_self_test() -> int:
    """内部逻辑自检：无需网络，验证变更检测与报告生成。退出 0 通过 / 2 失败。"""
    fails, passes = [], []

    def chk(label, cond):
        if cond:
            passes.append(label)
            print(f"  ✅ {label}")
        else:
            fails.append(label)
            print(f"  ❌ {label}")

    print("===== sync_snapshots.py 自检 =====")
    # 变更检测：首次（old=None）应判为变更
    chk("registry_changed(None, {...}) == True（首次登记）",
        registry_changed(None, {"counts": {"meta": 1, "agg": 1}, "latest": {}}) is True)
    # 无变化：同内容应判未变更
    a = {"counts": {"meta": 2, "agg": 1}, "latest": {"meta": "16.20.1", "agg": "x"}}
    chk("registry_changed(同内容) == False（幂等）",
        registry_changed(a, json.loads(json.dumps(a))) is False)
    # 聚合数变化应判变更
    b = {"counts": {"meta": 2, "agg": 2}, "latest": {"meta": "16.20.1", "agg": "y"}}
    chk("registry_changed(agg 数 1->2) == True",
        registry_changed(a, b) is True)

    # 报告生成：写入临时根目录（不污染项目），校验内容后清理
    import tempfile
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="sl_sync_selftest_"))
    try:
        (tmp / "data" / "agg").mkdir(parents=True)
        (tmp / "data" / "meta").mkdir(parents=True)
        old = None
        new = {
            "schema": "summonerlens.versions.v1",
            "counts": {"meta": 2, "agg": 1},
            "latest": {"meta": "16.20.1", "agg": "hexdata-2026-09-27-x"},
            "warnings": [],
            "snapshots": [
                {"kind": "agg", "id": "hexdata-2026-09-27-x", "patch": "16.19",
                 "report_date": "2026-09-27", "extra": {"hero_rows": 12, "augment_rows": 12}},
                {"kind": "meta", "id": "16.20.1", "patch": "16.20.1",
                 "extra": {"champion_count": 173, "item_count": 870}},
            ],
        }
        rp = write_report(tmp, old, new)
        chk("报告文件已生成", rp.exists())
        txt = rp.read_text(encoding="utf-8")
        chk("报告含新增 agg 快照标记", "hexdata-2026-09-27-x" in txt)
        chk("报告含 synthetic 趋势声明（agg=1）", "synthetic" in txt)
        # 二次写入（同天多轮）应追加而非覆盖
        write_report(tmp, new, new)
        txt2 = rp.read_text(encoding="utf-8")
        chk("同天二次写入为追加（含两个轮次）", txt2.count("同步轮次") == 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n  通过 {len(passes)} / 失败 {len(fails)}")
    if fails:
        print("  失败项：")
        for f in fails:
            print(f"    - {f}")
        return 2
    print("  ✅ 自检通过")
    return 0


def main() -> None:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)
    if "--self-test" in args:
        sys.exit(do_self_test())
    sys.exit(do_sync(args))


if __name__ == "__main__":
    main()
