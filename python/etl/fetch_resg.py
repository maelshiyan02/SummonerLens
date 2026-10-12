# -*- coding: utf-8 -*-
"""RESG · 公开聚合统计抓取（合规 · 版本化快照）。

来源：https://resg.top/api/v1/versions/<ver>/{champions,augments}.js
注：RESG 返回 ES module（export default {...}），需剥离前缀后 json.loads。
许可边界：只读公开数据；不绕过反爬、不批量转载、不商用。

用法：
  python python/etl/fetch_resg.py                       # 抓全部版本（versions.js 中列出）
  python python/etl/fetch_resg.py --ver=16.20           # 只抓指定版本
  python python/etl/fetch_resg.py --force               # 强制重抓（已存在版本也重下）
  python python/etl/fetch_resg.py --check               # 只校验本地已有快照的字段完整性

输出（相对项目根）：
  data/agg_resg/<ver>/champions.json        173 英雄完整胜率/场次/tier
  data/agg_resg/<ver>/augments.json         211 海克斯完整胜率/登场率/tier/quality
  data/agg_resg/<ver>/citation.json         引用溯源
  data/agg_resg/<ver>/raw/*.js              原始 ES module（调试用）
  data/agg_resg/LATEST                      指向最新版本号

设计纪律：
  - 项目根由脚本自身位置推导（python/etl/xxx.py -> parents[2]）。
  - 只依赖 Python 标准库；抓外部 JSON **curl 优先**（本机代理 CA 问题）。
  - ES module 前缀用正则剥离（export default 后跟空格/换行均可）。
  - 版本已存在则跳过（--force 可重抓）。
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

RESG_BASE = "https://resg.top/api/v1"
SITE = "RESG"
SITE_URL = "https://resg.top"
UA = "SummonerLens/0.1 (+resg etl; maelshiyan02)"

# ES module 前缀：export default 后可跟任意空白（空格/换行/tab）
ESM_PREFIX = re.compile(r'^export\s+default\s+', re.DOTALL)

# 字段最小契约（低于此数视为失败）
MIN_CHAMPIONS = 150
MIN_AUGMENTS = 180


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """curl 优先（本机走系统/代理 CA），回退 urllib。"""
    try:
        out = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout), "--noproxy", "*",
             "-H", f"User-Agent: {UA}", url],
            capture_output=True, timeout=timeout + 15)
        if out.returncode == 0 and out.stdout:
            return out.stdout
    except Exception:  # noqa: BLE001
        pass
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url: str, retries: int = 3, timeout: int = 60) -> dict:
    """抓取 URL，剥离 ES module 前缀，返回 dict/list。"""
    last = None
    for i in range(retries):
        try:
            raw = _fetch_bytes(url, timeout).decode("utf-8")
            stripped = ESM_PREFIX.sub("", raw.strip())
            return json.loads(stripped)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def get_bytes(url: str, retries: int = 3, timeout: int = 60) -> bytes:
    """只抓原始字节（用于调试 raw 缓存）。"""
    last = None
    for i in range(retries):
        try:
            return _fetch_bytes(url, timeout)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def list_versions() -> list:
    """获取 RESG 可用版本列表，按 collectedAt 倒序。"""
    data = get_json(f"{RESG_BASE}/versions.js")
    return sorted(data, key=lambda x: x.get("collectedAt", ""), reverse=True)


def _validate_entity(data: dict, entity: str, min_count: int) -> list:
    """校验 champions/augments 返回结构。"""
    problems = []
    items = data.get("items") or data  # RESG 外层包了 {items:[...]}
    count = len(items) if isinstance(items, list) else 0
    if count < min_count:
        problems.append(f"{entity} 数量不足：{count} < {min_count}")
    if count == 0:
        problems.append(f"{entity} 返回空列表")
    # 抽样字段检查
    if count > 0:
        sample = items[0]
        required = {
            "champions": ["id", "name", "wr", "tm", "wm", "tier"],
            "augments": ["id", "name", "wr", "tm", "wm", "pr", "tier", "quality"],
        }[entity]
        missing = [k for k in required if sample.get(k) is None]
        if missing:
            problems.append(f"{entity} 字段缺失：{missing}")
    return problems


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list, cols: list) -> None:
    import csv
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# --------------------------------------------------------------------------- core
def fetch_version(root: Path, ver: str, force: bool = False) -> dict:
    """抓取单个版本的 champions + augments。返回抓取摘要。"""
    out_dir = root / "data" / "agg_resg" / ver
    raw_dir = out_dir / "raw"
    ch_fp = out_dir / "champions.json"
    aug_fp = out_dir / "augments.json"
    cit_fp = out_dir / "citation.json"

    if ch_fp.exists() and aug_fp.exists() and not force:
        print(f"[resg] 版本 {ver} 已存在，跳过（--force 可重抓）")
        return {"version": ver, "skipped": True}

    print(f"[resg] 抓取版本 {ver} ...")
    summary = {"version": ver, "collected_at": None, "champions_count": 0, "augments_count": 0}

    # champions
    ch_url = f"{RESG_BASE}/versions/{ver}/champions.js"
    ch_raw = get_bytes(ch_url)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "champions.js").write_bytes(ch_raw)
    ch_data = json.loads(ESM_PREFIX.sub("", ch_raw.decode("utf-8").strip()))
    problems = _validate_entity(ch_data, "champions", MIN_CHAMPIONS)
    if problems:
        for p in problems:
            print(f"  ❌ {p}")
        raise SystemExit(1)
    items = ch_data.get("items")
    _write_json(ch_fp, items)
    summary["champions_count"] = len(items)

    # augments
    aug_url = f"{RESG_BASE}/versions/{ver}/augments.js"
    aug_raw = get_bytes(aug_url)
    (raw_dir / "augments.js").write_bytes(aug_raw)
    aug_data = json.loads(ESM_PREFIX.sub("", aug_raw.decode("utf-8").strip()))
    problems = _validate_entity(aug_data, "augments", MIN_AUGMENTS)
    if problems:
        for p in problems:
            print(f"  ❌ {p}")
        raise SystemExit(1)
    items = aug_data.get("items")
    _write_json(aug_fp, items)
    summary["augments_count"] = len(items)

    # citation
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    citation = {
        "source": SITE,
        "source_url": SITE_URL,
        "resg_version": ver,
        "resg_base": RESG_BASE,
        "fetched_at": fetched_at,
        "usage_policy": {
            "retrieval": "allowed (public read-only)",
            "bulk_republish": "disallowed",
            "commercial": "disallowed",
            "license_note": "RESG 未声明开放许可，本项目仅读取公开聚合端点用于分析展示，引用须标注来源。",
        },
        "attribution_text": (
            f"数据来源：{SITE}（{SITE_URL}）｜Patch: {ver}"
            f"｜抓取日期: {fetched_at}"),
    }
    summary["collected_at"] = fetched_at
    _write_json(cit_fp, citation)

    print(f"[resg] ✅ {ver}: {summary['champions_count']} 英雄 / {summary['augments_count']} 海克斯")
    return summary


def do_check(root: Path) -> int:
    """只校验本地快照（--check）。"""
    latest = root / "data" / "agg_resg" / "LATEST"
    if not latest.exists():
        print("[resg] 本地无快照（LATEST 不存在）")
        return 1
    ver = latest.read_text(encoding="utf-8").strip()
    ch_fp = root / "data" / "agg_resg" / ver / "champions.json"
    aug_fp = root / "data" / "agg_resg" / ver / "augments.json"
    cit_fp = root / "data" / "agg_resg" / ver / "citation.json"
    ok = True
    for label, fp in [("champions", ch_fp), ("augments", aug_fp), ("citation", cit_fp)]:
        if not fp.exists():
            print(f"[resg] ❌ {label} 缺失: {fp}")
            ok = False
    if not ok:
        return 1
    ch = json.loads(ch_fp.read_text(encoding="utf-8"))
    aug = json.loads(aug_fp.read_text(encoding="utf-8"))
    cit = json.loads(cit_fp.read_text(encoding="utf-8"))
    print(f"[resg] 版本 = {ver}")
    print(f"[resg] 英雄 = {len(ch)} / 海克斯 = {len(aug)}")
    print(f"[resg] citation.source = {cit.get('source')}")
    if len(ch) < MIN_CHAMPIONS or len(aug) < MIN_AUGMENTS:
        print("[resg] ❌ 数量低于契约阈值")
        return 1
    print("[resg] ✅ 本地快照完整")
    return 0


def _update_latest(root: Path, ver: str) -> None:
    latest = root / "data" / "agg_resg" / "LATEST"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(ver, encoding="utf-8")


# --------------------------------------------------------------------------- main
def main() -> None:
    root = project_root()
    args = sys.argv[1:]
    force = "--force" in args

    if "--check" in args:
        sys.exit(do_check(root))

    target_ver = None
    for a in args:
        if a.startswith("--ver="):
            target_ver = a.split("=", 1)[1]

    print(f"[resg] 基础地址 {RESG_BASE}")

    if target_ver:
        print(f"[resg] 指定版本 {target_ver}")
        fetch_version(root, target_ver, force=force)
        _update_latest(root, target_ver)
    else:
        versions = list_versions()
        print(f"[resg] 可用版本 {[v['version'] for v in versions]}")
        last_ok = None
        for v in versions:
            res = fetch_version(root, v["version"], force=force)
            if not res.get("skipped"):
                last_ok = v["version"]
        if last_ok:
            _update_latest(root, last_ok)

    print("[resg] ✅ 完成")


if __name__ == "__main__":
    main()
