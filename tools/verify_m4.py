# -*- coding: utf-8 -*-
"""M4 · 可视化与桌面壳 端到端验收

覆盖：
  A 离线资源（无 CDN 外链、ECharts 已内置且校验和一致）
  B 数据束 schema 与来源标注（真实聚合 / 合成夹具 严格分区）
  C 内容一致性（与 data/agg 源 CSV、meta CSV 独立比对 + Wilson 独立重算）
  D 本地服务（127.0.0.1 回环、静态资源、/api/health、/api/rebuild）
  E 前端逻辑（node 加载 core.js 并跑单测）
  F 桌面壳（pubspec 依赖、关键源文件、URL 参数驱动；--with-flutter 追加 analyze/test）
  G 渲染抽查（--with-render 用 Chrome headless 出图，需本地服务）

用法：
  python tools/verify_m4.py                 默认（A~E + F 静态部分）
  python tools/verify_m4.py --with-flutter  追加 flutter analyze / flutter test
  python tools/verify_m4.py --with-render   追加 Chrome headless 截图
  python tools/verify_m4.py --self-test     故障注入：只改**输入**、判据不变 → 必须变红
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from stats import wilson  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web"
VER = "16.20.1"

PASS = 0
FAIL = 0
FAILED = []
SKIPPED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"  ✗ {name}" + (f"   [{detail}]" if detail else ""))


def skip(name, why=""):
    SKIPPED.append(name)
    print(f"  – {name}（跳过：{why}）")


def read_csv(p: Path):
    import csv
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


EXT_URL = re.compile(rb"""(?:src|href)\s*=\s*["']https?://""", re.I)
BARE_URL = re.compile(rb"""https?://[a-z0-9.-]+/""", re.I)


# ---------------------------------------------------------------------------- 环境（故障注入改这里）
class Env:
    def __init__(self, self_test: bool):
        self.self_test = self_test
        self.tmp = None
        self.bundle_path = WEB / "data" / "dashboard.json"
        self.html_path = WEB / "index.html"
        self.echarts_path = WEB / "vendor" / "echarts.min.js"
        if self_test:
            self.tmp = Path(tempfile.mkdtemp(prefix="m4_selftest_"))
            b = json.loads(self.bundle_path.read_text(encoding="utf-8"))
            # 篡改 1：夹具数据集谎报为真实聚合
            b["dataset_index"]["fixture_hero_stats"]["kind"] = "real_aggregate"
            # 篡改 2：删掉真实英雄榜
            b["datasets"].pop("hero_ranking", None)
            b["dataset_index"].pop("hero_ranking", None)
            # 篡改 3：抹掉 hexdata 引用
            b["hexdata_citation"]["buildId"] = None
            # 篡改 4：打乱别名索引
            b["alias_index"] = {}
            # 篡改 5：篡改名次数值（应被 Wilson 独立重算抓到）
            if "augment_ranking" in b["datasets"]:
                b["datasets"]["augment_ranking"]["rows"][0]["wilson_lower"] += 0.5
            # 篡改 7：删掉版本注册表（M5 字段，应被 schema 断言抓到）—— 须在写盘前
            b.pop("versions", None)
            self.bundle_path = self.tmp / "dashboard.json"
            self.bundle_path.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
            # 篡改 6：HTML 混入 CDN 外链
            html = (WEB / "index.html").read_text(encoding="utf-8")
            html = html.replace("vendor/echarts.min.js",
                                "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js")
            self.html_path = self.tmp / "index.html"
            self.html_path.write_text(html, encoding="utf-8")

    def bundle(self):
        return json.loads(self.bundle_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- A 离线资源
def sec_a(env: Env):
    print("\n[A] 离线资源（可离线、无外链、许可可查）")
    check("index.html 存在", env.html_path.exists(), str(env.html_path))
    if env.html_path.exists():
        raw = env.html_path.read_bytes()
        check("index.html 无外部 http(s) 脚本/链接", EXT_URL.search(raw) is None,
              "发现 CDN 外链")
    check("index.html 引用了本地 core.js 与 app.js",
          b"js/core.js" in raw and b"js/app.js" in raw)
    check("index.html 引用了本地 echarts", b"vendor/echarts.min.js" in raw)
    check("index.html 引用内联数据束（file:// 双击可用）", b"data/dashboard.js" in raw)

    js_bundle = WEB / "data" / "dashboard.js"
    check("内联数据束 data/dashboard.js 存在", js_bundle.exists())
    if js_bundle.exists():
        txt = js_bundle.read_text(encoding="utf-8")
        check("内联数据束定义 window.__SL_BUNDLE__", "__SL_BUNDLE__" in txt)
        try:
            payload = txt.split("=", 1)[1].strip().rstrip(";")
            check("内联数据束与 JSON 数据束内容一致（防陈旧）",
                  json.loads(payload) == env.bundle())
        except (ValueError, json.JSONDecodeError) as e:
            check("内联数据束可解析", False, str(e))
    for js in ("core.js", "app.js"):
        p = WEB / "js" / js
        check(f"js/{js} 存在", p.exists())
        if p.exists():
            check(f"js/{js} 无外部 http(s) 引用", EXT_URL.search(p.read_bytes()) is None)

    check("vendor/echarts.min.js 存在", env.echarts_path.exists())
    if env.echarts_path.exists():
        size = env.echarts_path.stat().st_size
        check("ECharts 体积合理（>500KB 表示完整包）", size > 500_000, f"{size} 字节")
        sha_file = WEB / "vendor" / "echarts.sha256.txt"
        if sha_file.exists():
            recorded = sha_file.read_text(encoding="utf-8").split()[0].strip()
            check("ECharts sha256 与记录一致", sha256(env.echarts_path) == recorded,
                  f"记录 {recorded[:12]}…")
        else:
            skip("ECharts 校验和比对", "缺少 echarts.sha256.txt")
        lic = (WEB / "vendor" / "echarts.LICENSE.txt")
        check("ECharts LICENSE 存在且为 Apache-2.0",
              lic.exists() and b"Apache License" in lic.read_bytes())
        pkg = WEB / "vendor" / "echarts.package.json"
        if pkg.exists():
            meta = json.loads(pkg.read_text(encoding="utf-8"))
            check("ECharts 包元信息声明 Apache-2.0",
                  meta.get("license") == "Apache-2.0", str(meta.get("license")))
            check("ECharts 版本已固定（5.x）", str(meta.get("version", "")).startswith("5."),
                  str(meta.get("version")))
        else:
            skip("ECharts 包元信息", "缺少 echarts.package.json")


# ---------------------------------------------------------------------------- B 数据束 schema
def sec_b(env: Env):
    print("\n[B] 数据束 schema 与来源标注（合规硬要求）")
    b = env.bundle()
    check("schema = summonerlens.dashboard.v1", b.get("schema") == "summonerlens.dashboard.v1")
    check("rank_method 与 M3 一致",
          b.get("rank_method") == "sample_tier_then_wilson_lower_bound_v1")
    check("meta_version 非空", bool(b.get("meta_version")))
    idx = b.get("dataset_index", {})
    check("数据集索引非空", len(idx) > 0)
    check("所有数据集 kind 取值合法",
          all(v.get("kind") in ("real_aggregate", "real_aggregate_resg",
                                 "synthetic_fixture", "unavailable") for v in idx.values()),
          str({k: v.get("kind") for k, v in idx.items()}))
    check("真实数据集标注为 real_aggregate",
          idx.get("hero_ranking", {}).get("kind") == "real_aggregate"
          and idx.get("augment_ranking", {}).get("kind") == "real_aggregate")
    check("夹具数据集标注为 synthetic_fixture",
          all(idx.get(k, {}).get("kind") == "synthetic_fixture"
              for k in idx if k.startswith("fixture_")))
    empty = [k for k, v in idx.items()
             if not v.get("rows") and v.get("kind") != "unavailable"]
    check("无空数据集（空结果判 FAIL，unavailable 豁免）", not empty, f"空：{empty}")
    check("bundle.warnings 非空", len(b.get("warnings") or []) > 0)
    check("warnings 明确警示合成夹具不得对外",
          any("合成夹具" in w or "synthetic" in w for w in (b.get("warnings") or [])))
    cit = b.get("hexdata_citation") or {}
    check("hexdata 引用四字段齐备",
          all(cit.get(k) for k in ("buildId", "reportPatch", "reportDate")),
          str(cit.get("buildId")))

    # M5 版本化维度（前端离线消费）
    vidx = b.get("versions") or {}
    check("bundle.versions 注册表存在且有快照",
          bool(vidx.get("snapshots")), str(vidx.get("counts")))
    check("bundle.metas 含 ≥2 版本英雄字典（离线切换）",
          len((b.get("metas") or {}).keys()) >= 2, str(list((b.get("metas") or {}).keys())))
    vc = b.get("version_changes") or []
    check("bundle.version_changes 非空（相邻 meta 对）", len(vc) >= 1)
    check("version_changes 含真实 diff（status=ok）",
          any(x.get("status") == "ok" for x in vc))
    tr = b.get("trend") or {}
    check("bundle.trend 含 kind 与 builds 字段",
          bool(tr.get("kind")) and isinstance(tr.get("builds"), list))
    check("bundle.risk_notes 为列表", isinstance(b.get("risk_notes") or [], list))


# ---------------------------------------------------------------------------- C 内容一致性
def sec_c(env: Env):
    print("\n[C] 内容一致性（与源 CSV / M3 独立比对）")
    b = env.bundle()
    ds = b.get("datasets", {})

    agg = ROOT / "data" / "agg"
    latest = agg / "LATEST"
    if latest.exists():
        adir = agg / latest.read_text(encoding="utf-8").strip()
        src_hero = read_csv(adir / "top_heroes.csv")
        src_aug = read_csv(adir / "top_augments.csv")
        hr = ds.get("hero_ranking", {}).get("rows", [])
        ar = ds.get("augment_ranking", {}).get("rows", [])
        check("英雄榜行数 == 源 top_heroes.csv 行数", len(hr) == len(src_hero),
              f"{len(hr)} vs {len(src_hero)}")

        # 独立重算 Wilson，逐行比对（名次数值不可手改）
        src_rows = [{"key": int(r["id"]), "games": int(float(r["games"])),
                     "winRate": float(r["winRate"]),
                     "wins": int(round(float(r["winRate"]) * float(r["games"])))} for r in src_hero]
        recomputed = {r["key"]: r for r in wilson.rank_entities(src_rows, wilson.METHOD_TIER_THEN_WILSON)}
        mismatch = []
        for r in hr:
            ref = recomputed.get(r["key"])
            if not ref or abs(ref["wilson_lower"] - r["wilson_lower"]) > 1e-9 \
                    or ref["rank"] != r["rank"]:
                mismatch.append(r["key"])
        check("英雄榜 Wilson 下界与名次 = 独立重算结果", not mismatch, f"不符：{mismatch[:5]}")

        aug_rows = [{"key": int(r["id"]), "games": int(float(r["games"])),
                     "winRate": float(r["winRate"]),
                     "wins": int(round(float(r["winRate"]) * float(r["games"])))} for r in src_aug]
        rec_aug = {r["key"]: r for r in wilson.rank_entities(aug_rows, wilson.METHOD_TIER_THEN_WILSON)}
        mm = [r["key"] for r in ar
              if r["key"] not in rec_aug
              or abs(rec_aug[r["key"]]["wilson_lower"] - r["wilson_lower"]) > 1e-9]
        check("Augment 榜 Wilson 下界 = 独立重算结果", not mm, f"不符：{mm[:5]}")
        check("Augment 榜行数 == 源 top_augments.csv 行数", len(ar) == len(src_aug))
    else:
        skip("与 hexdata 源 CSV 比对", "data/agg/LATEST 缺失")

    champs = read_csv(ROOT / "data" / "meta" / VER / "champions.csv")
    augs = read_csv(ROOT / "data" / "meta" / VER / "augments.csv")
    check("英雄字典数量 == champions.csv 行数",
          len(b.get("heroes", [])) == len(champs), f"{len(b.get('heroes', []))} vs {len(champs)}")
    check("夹具英雄统计行数 == champions.csv 行数",
          ds.get("fixture_hero_stats", {}).get("rows")
          and len(ds["fixture_hero_stats"]["rows"]) == len(champs))
    check("夹具 Augment 统计行数 == augments.csv 行数",
          len(ds.get("fixture_augment_stats", {}).get("rows", [])) == len(augs))

    hero_keys = {h["key"] for h in b.get("heroes", [])}
    ai = b.get("alias_index", {})
    check("别名索引非空", len(ai) > 100, f"{len(ai)} 条")
    bad = [k for k, v in ai.items() if v not in hero_keys]
    check("别名索引全部指向存在的英雄 key", not bad, f"悬空：{bad[:5]}")
    check("任一英雄的别名包含其正式名",
          all(any(a == h["name"] for a in h.get("aliases", [])) for h in b.get("heroes", [])))
    # 关键别名抽查（中文刚需）
    for alias, key in (("快乐风男", 157), ("亚索", 157), ("tf", 4), ("火女", 1)):
        check(f"别名抽查 {alias} → {key}", ai.get(alias) == key, str(ai.get(alias)))
    check("夹具来源标注为 synthetic_fixture",
          ds.get("fixture_hero_stats", {}).get("prov", {}).get("kind") == "synthetic_fixture")


# ---------------------------------------------------------------------------- D 本地服务
def start_server() -> (subprocess.Popen, str):
    py = sys.executable
    proc = subprocess.Popen(
        [py, str(ROOT / "python" / "bridge" / "serve.py"), "--port=0"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace")
    url = None
    t0 = time.time()
    while time.time() - t0 < 150:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        if line.startswith("SUMMONERLENS_SERVE"):
            url = line.split(" ", 1)[1].strip()
            break
    return proc, url


def http_get(url: str, timeout=20):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def http_post(url: str, timeout=180):
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def sec_d(env: Env, allow: bool):
    print("\n[D] 本地服务（仅回环、静态资源、health、rebuild）")
    if not allow:
        skip("本地服务检查", "已禁用")
        return
    proc, url = start_server()
    try:
        check("serve.py 打印装载地址", bool(url), "未捕获到 SUMMONERLENS_SERVE 行")
        if not url:
            return
        check("服务仅绑定 127.0.0.1（不对外暴露）",
              url.startswith("http://127.0.0.1:"), url)
        st, body = http_get(url)
        check("GET / → 200", st == 200, str(st))
        check("GET / 返回仪表板 HTML", b"SummonerLens" in body and b"echarts" in body)
        st, body = http_get(url + "api/health")
        health = json.loads(body)
        check("/api/health ok=true", health.get("ok") is True, str(health)[:120])
        st, body = http_get(url + "data/dashboard.json")
        served = json.loads(body)
        check("服务提供的 bundle schema 正确",
              served.get("schema") == "summonerlens.dashboard.v1")
        st, body = http_get(url + "js/core.js")
        check("GET /js/core.js → 200", st == 200 and b"SLCore" in body)
        st, body = http_get(url + "vendor/echarts.min.js")
        check("GET /vendor/echarts.min.js → 200 且完整", st == 200 and len(body) > 500_000,
              f"{len(body)} 字节")
        st, body = http_post(url + "api/rebuild")
        rb = json.loads(body)
        check("POST /api/rebuild → ok（联动数据层重建）", rb.get("ok") is True, str(rb)[:120])
        check("重建后数据束仍合法",
              json.loads((WEB / "data" / "dashboard.json").read_text(encoding="utf-8"))
              .get("schema") == "summonerlens.dashboard.v1")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        check("本地服务可用（无异常）", False, str(e))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------- E 前端逻辑
def sec_e(env: Env):
    print("\n[E] 前端逻辑（node 加载 core.js 并跑单测）")
    node = shutil.which("node")
    if not node:
        for c in (r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-6\node.exe",):
            if Path(c).exists():
                node = c
                break
    if not node:
        skip("node 单测", "未找到 node")
        return
    # 直接加载 core.js，验证导出面与别名链路
    script = (
        "const C=require(process.argv[1]);"
        "const b=JSON.parse(require('fs').readFileSync(process.argv[2],'utf8'));"
        "const api=['decodeAlias','searchHeroes','filterByTier','buildRankingOption',"
        "'buildSynergyHeatmapOption','buildMmrHistogramOption','kpis','rowLabel',"
        "'heroNameInMeta','buildChangesSummaryOption','buildTrendOption'];"
        "const miss=api.filter(k=>typeof C[k]!=='function');"
        "const r={missing:miss,alias:C.decodeAlias(b.alias_index,'快乐风男'),"
        "coreVersion:C.VERSION,"
        "trend:C.buildTrendOption(b.trend,{}).series.length,"
        "chg:C.buildChangesSummaryOption((b.version_changes[0]||{}).summary||{}).xAxis.data.length,"
        "name:(function(){var ks=Object.keys(b.metas||{});if(!ks.length)return null;"
        "var vk=ks[0];var hk=b.metas[vk].heroes[0].key;"
        "return C.heroNameInMeta(b,hk,vk);})()};"
        "console.log(JSON.stringify(r));"
    )
    r = subprocess.run([node, "-e", script, str(WEB / "js" / "core.js"),
                        str(env.bundle_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        check("core.js 可被 node 加载", False, (r.stdout or r.stderr)[:160])
        return
    check("core.js 可被 node 加载", r.returncode == 0)
    check("core.js 导出关键 API 齐备", not out["missing"], str(out["missing"]))
    check("core.js 声明版本", bool(out.get("coreVersion")))
    check("别名链路（node 侧）快乐风男 → 157", out.get("alias") == 157, str(out.get("alias")))
    check("core.js 导出 M5 API（趋势/变更/名解析）齐备", not out.get("missing"),
          str(out.get("missing")))
    check("buildTrendOption 返回多序列（序列数>0）", (out.get("trend") or 0) > 0, str(out.get("trend")))
    check("buildChangesSummaryOption 返回 5 类目", out.get("chg") == 5, str(out.get("chg")))
    check("heroNameInMeta 解析真实英雄名", bool(out.get("name")), str(out.get("name")))

    ut = subprocess.run([node, str(ROOT / "tools" / "test_m4_unit.js")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("tools/test_m4_unit.js 全绿（退出码 0）", ut.returncode == 0,
          (ut.stdout or "")[-200:])


# ---------------------------------------------------------------------------- F 桌面壳
def sec_f(env: Env, with_flutter: bool):
    print("\n[F] 桌面壳（Flutter）")
    pubspec = ROOT / "app" / "pubspec.yaml"
    check("app/pubspec.yaml 存在", pubspec.exists())
    if pubspec.exists():
        txt = pubspec.read_text(encoding="utf-8")
        check("依赖含 webview_windows（内嵌 WebView2）", "webview_windows" in txt)
        check("依赖含 url_launcher（浏览器兜底）", "url_launcher" in txt)
    for rel in ("lib/main.dart", "lib/theme.dart", "lib/pages/shell_page.dart",
                "lib/services/bridge_service.dart", "lib/services/python_locator.dart",
                "lib/widgets/dashboard_webview.dart"):
        check(f"{rel} 存在", (ROOT / "app" / rel).exists())

    shell = ROOT / "app" / "lib" / "pages" / "shell_page.dart"
    if shell.exists():
        s = shell.read_text(encoding="utf-8")
        check("壳通过 URL 查询参数驱动仪表板（tab/dataset 联动）",
              "tab=" in s and "dataset=" in s)
        check("壳拉起 Python bridge（本地服务）", "serve.py" in s or "BridgeService" in s)
        check("深色默认主题已接（SLTheme.dark）",
              "SLTheme.dark" in (ROOT / "app" / "lib" / "main.dart").read_text(encoding="utf-8"))
    nav = ROOT / "app" / "lib" / "pages" / "shell_page.dart"
    if nav.exists():
        s = nav.read_text(encoding="utf-8")
        check("左侧导航四页齐备（概览/排名/协同/分层）",
              all(k in s for k in ("概览", "排名", "协同", "分层")))
    testf = ROOT / "app" / "test" / "summonerlens_test.dart"
    check("存在 dart 单测文件", testf.exists())

    # M5-4 前端：版本选择器 + 「版本/趋势」标签页 + ?ver= 深链
    web_idx = WEB / "index.html"
    if web_idx.exists():
        wi = web_idx.read_text(encoding="utf-8")
        check("前端含版本选择器 sel-ver", 'id="sel-ver"' in wi)
        check("前端含「版本/趋势」标签页", 'data-tab="version"' in wi)
        check("前端含版本变更面板 panel-version", 'id="panel-version"' in wi)
        check("前端含聚合趋势图位 chart-trend", 'id="chart-trend"' in wi)
    ajs = WEB / "js" / "app.js"
    if ajs.exists():
        a = ajs.read_text(encoding="utf-8")
        check("app.js 实现版本选择器与渲染（metaVersion/sel-ver/renderVersion）",
              all(k in a for k in ("metaVersion", "sel-ver", "renderVersion")))
        check("app.js 支持 ?ver= 深链参数", "'ver'" in a)

    ft = ROOT / "tools" / "flutter_task.py"
    check("存在 flutter 任务入口（禁止裸跑 flutter/dart）", ft.exists())
    if ft.exists():
        check("flutter 任务入口覆盖 analyze/build/test",
              all(k in ft.read_text(encoding="utf-8") for k in ('"analyze"', '"build"', '"test"')))
    check("存在 headless 校验入口 tools/run_headless_task.py",
          (ROOT / "tools" / "run_headless_task.py").exists())

    if not with_flutter:
        skip("flutter analyze / flutter test", "未加 --with-flutter")
        return
    for task, label in (("analyze", "flutter analyze 无 issue"),
                        ("test", "flutter test 全绿")):
        r = subprocess.run([sys.executable, str(ft), task], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(label, r.returncode == 0, (r.stdout or "")[-200:])


# ---------------------------------------------------------------------------- G 渲染抽查
def sec_g(env: Env, allow: bool):
    print("\n[G] 渲染抽查（Chrome headless 出图）")
    if not allow:
        skip("Chrome headless 渲染", "未加 --with-render")
        return
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        skip("Chrome headless 渲染", "未找到 chrome.exe")
        return
    proc, url = start_server()
    try:
        if not url:
            check("Chrome 渲染前置：本地服务可用", False, "服务未启动")
            return
        outdir = ROOT / "build" / "verify"
        outdir.mkdir(parents=True, exist_ok=True)
        ok = True
        for name, qs in (("verify_overview", ""),
                         ("verify_ranking", "?dataset=fixture&tab=ranking"),
                         ("verify_synergy", "?dataset=fixture&tab=synergy"),
                         ("verify_strata", "?dataset=fixture&tab=strata")):
            png = outdir / f"{name}.png"
            subprocess.run([str(chrome), "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--hide-scrollbars", "--window-size=1680,1050",
                            "--virtual-time-budget=9000",
                            f"--user-data-dir={outdir / ('p_' + name)}",
                            f"--screenshot={png}", url + qs],
                           capture_output=True, timeout=120)
            ok = ok and png.exists() and png.stat().st_size > 40_000
            print(f"     {name}: {png.stat().st_size if png.exists() else 0} 字节")
        check("四个视图均产出非空渲染图（>40KB）", ok)
    except (OSError, subprocess.TimeoutExpired) as e:
        check("Chrome headless 渲染", False, str(e))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--with-flutter", action="store_true")
    ap.add_argument("--with-render", action="store_true")
    ap.add_argument("--no-server", action="store_true")
    args = ap.parse_args()

    if not (WEB / "data" / "dashboard.json").exists():
        print("❌ 缺少数据束。先运行：python python/bridge/build_viz_bundle.py")
        return 2

    env = Env(args.self_test)
    print("=" * 64)
    print(f"M4 验收 · {'故障注入 --self-test' if args.self_test else '正常'} · {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)
    sec_a(env)
    sec_b(env)
    sec_c(env)
    sec_d(env, allow=not args.no_server and not args.self_test)
    sec_e(env)
    sec_f(env, with_flutter=args.with_flutter and not args.self_test)
    sec_g(env, allow=args.with_render and not args.self_test)

    if env.tmp and env.tmp.exists():
        shutil.rmtree(env.tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"结果：{PASS} PASS / {FAIL} FAIL" + (f" / {len(SKIPPED)} SKIP" if SKIPPED else ""))
    if FAILED:
        print("失败项：")
        for f in FAILED:
            print("  ✗ " + f)
    if args.self_test:
        if FAIL > 0:
            print("✅ 故障注入生效：断言真变红（退出码 1）")
            return 1
        print("❌ 故障注入无效：改了输入仍全绿 —— 断言没有分辨力！")
        return 3
    print("✅ 全部通过" if FAIL == 0 else "❌ 存在失败项")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
