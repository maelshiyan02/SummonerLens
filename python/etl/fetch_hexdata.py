# -*- coding: utf-8 -*-
"""M2 · hexdata 聚合统计抓取（合规 · 带溯源）。

来源：https://hexdata.com.cn/data/ai-summary.json
许可边界（robots.txt + citationPolicy，务必遵守）：
  - 检索式获取 ✅ allowed
  - 独立模型训练 ❌ / 批量转载 ❌ / 商用 ❌
  - 引用必须附：「数据来源：Hexdata（hexdata.com.cn）」+ canonical 链接 + buildId + reportPatch + reportDate

用法：
  python python/etl/fetch_hexdata.py            # 抓最新（buildId 已存在则跳过）
  python python/etl/fetch_hexdata.py --force    # 强制重抓
  python python/etl/fetch_hexdata.py --check    # 只校验本地已有快照的引用字段完整性

输出（相对项目根）：
  data/agg/<buildId>/raw/ai-summary.json      原始聚合 JSON（大，不入仓）
  data/agg/<buildId>/top_heroes.csv           热门英雄（含 winRate/pickRate/games/tier）
  data/agg/<buildId>/top_augments.csv         热门强化符文（含 globalHexScore/coverage）
  data/agg/<buildId>/hero_aliases.csv         英雄昵称（172 条）
  data/agg/<buildId>/methodology.json         口径（样本分档 / Wilson / 排序）
  data/agg/<buildId>/citation.json            引用溯源（四字段 + canonical 链接）
  data/agg/LATEST                           指向当前 buildId 的文本指针

设计纪律：
  - 项目根**由脚本自身位置推导**（python/etl/xxx.py -> parents[2]），不写绝对路径。
  - 只依赖 Python 标准库；抓外部 JSON **curl 优先**（本机代理 CA 问题，见 A09）。
  - 缺关键字段直接 SystemExit（不静默通过）。
"""
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HEXDATA = "https://hexdata.com.cn"
AI_SUMMARY_URL = f"{HEXDATA}/data/ai-summary.json"
SITE = "Hexdata"
SITE_URL = "https://hexdata.com.cn"
UA = "SummonerLens/0.1 (+hexdata etl; maelshiyan02)"

# 引用必须附带的四字段（citationPolicy.requiredContext）
REQUIRED_CONTEXT = ["buildId", "reportPatch", "reportDate"]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """curl 优先（本机走系统/代理 CA），回退 urllib。"""
    try:
        out = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout), "-H", f"User-Agent: {UA}", url],
            capture_output=True, timeout=timeout + 15)
        if out.returncode == 0 and out.stdout:
            return out.stdout
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url: str, retries: int = 3, timeout: int = 60) -> dict:
    last = None
    for i in range(retries):
        try:
            return json.loads(_fetch_bytes(url, timeout).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def _write_csv(path: Path, rows: list, cols: list) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def validate(doc: dict) -> list:
    """校验关键字段；返回问题列表（空 = OK）。"""
    problems = []
    for k in ["buildId", "reportPatch", "reportDate"]:
        if not doc.get(k):
            problems.append(f"缺少 {k}")
    cp = doc.get("citationPolicy") or {}
    if not cp:
        problems.append("缺少 citationPolicy")
    for req in cp.get("requiredContext", []) or []:
        if req not in doc or not doc.get(req):
            problems.append(f"citationPolicy.requiredContext 要求 {req}，但主体缺失")
    for k in ["topHeroes", "topAugments", "heroAliases"]:
        if not doc.get(k):
            problems.append(f"{k} 为空")
    return problems


def do_check(root: Path) -> int:
    """只校验本地快照（--check）。"""
    latest = root / "data" / "agg" / "LATEST"
    if not latest.exists():
        print("[hexdata] 本地无快照（LATEST 不存在）")
        return 1
    bid = latest.read_text(encoding="utf-8").strip()
    cit = root / "data" / "agg" / bid / "citation.json"
    if not cit.exists():
        print(f"[hexdata] 快照 {bid} 缺 citation.json")
        return 1
    c = json.loads(cit.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_CONTEXT if not c.get(k)]
    print(f"[hexdata] 快照 = {bid}")
    print(f"[hexdata] 引用四字段 = { {k: c.get(k) for k in REQUIRED_CONTEXT} }")
    if missing:
        print(f"[hexdata] ❌ 引用字段缺失：{missing}")
        return 1
    print("[hexdata] ✅ 引用字段完整")
    return 0


def main() -> None:
    root = project_root()
    args = sys.argv[1:]
    force = "--force" in args

    if "--check" in args:
        sys.exit(do_check(root))

    print(f"[hexdata] 抓取 {AI_SUMMARY_URL}")
    doc = get_json(AI_SUMMARY_URL)

    problems = validate(doc)
    if problems:
        print("[hexdata] ❌ 数据校验失败：")
        for p in problems:
            print(f"    - {p}")
        raise SystemExit(1)

    build_id = doc["buildId"]
    out_dir = root / "data" / "agg" / build_id
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    summary_file = out_dir / "top_heroes.csv"
    citation = {}
    if summary_file.exists() and not force:
        print(f"[hexdata] 快照已存在，跳过：{build_id}（--force 可强制重抓）")
        cit_fp = out_dir / "citation.json"
        if cit_fp.exists():
            try:
                citation = json.loads(cit_fp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                pass
    else:
        (raw_dir / "ai-summary.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

        _write_csv(out_dir / "top_heroes.csv", doc["topHeroes"],
                   ["id", "name", "alternateNames", "url", "winRate", "pickRate", "games", "tier"])
        _write_csv(out_dir / "top_augments.csv", doc["topAugments"],
                   ["id", "name", "url", "globalHexScore", "winRate", "pickRate", "games", "coverageHeroCount"])
        _write_csv(out_dir / "hero_aliases.csv", doc["heroAliases"],
                   ["id", "name", "alternateNames", "url"])

        (out_dir / "methodology.json").write_text(
            json.dumps({
                "methodology": doc.get("methodology"),
                "patchComparison": doc.get("patchComparison"),
                "economyRanking": doc.get("economyRanking"),
                "riskNotes": doc.get("riskNotes"),
                "license": doc.get("license"),
                "isBasedOn": doc.get("isBasedOn"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        # 引用溯源（四字段 + canonical）
        cp = doc.get("citationPolicy") or {}
        citation = {
            "source": SITE,
            "source_url": SITE_URL,
            "canonical_pages": doc.get("canonicalPages"),
            "preferred_canonical_urls": cp.get("preferredCanonicalUrls"),
            "attribution": cp.get("attribution"),
            "attribution_required": cp.get("attributionRequired", True),
            "required_context": REQUIRED_CONTEXT,
            "buildId": doc.get("buildId"),
            "reportPatch": doc.get("reportPatch"),
            "reportDate": doc.get("reportDate"),
            "generatedAt": doc.get("generatedAt"),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "license": doc.get("license"),
            "usage_policy": {
                "retrieval": "allowed",
                "model_training": "disallowed",
                "bulk_republish": "disallowed",
                "commercial": "disallowed",
            },
            "attribution_text": (
                f"数据来源：{SITE}（{SITE_URL}）｜Build: {doc.get('buildId')}"
                f"｜Patch: {doc.get('reportPatch')}｜数据日期: {doc.get('reportDate')}"),
        }
        (out_dir / "citation.json").write_text(
            json.dumps(citation, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[hexdata] 已落地 -> {out_dir}")

    # LATEST 指针
    (root / "data" / "agg" / "LATEST").write_text(build_id, encoding="utf-8")

    print(f"[hexdata] buildId = {build_id}")
    print(f"[hexdata] patch = {doc.get('reportPatch')} / date = {doc.get('reportDate')}")
    print(f"[hexdata] topHeroes = {len(doc.get('topHeroes', []))} | "
          f"topAugments = {len(doc.get('topAugments', []))} | "
          f"heroAliases = {len(doc.get('heroAliases', []))}")
    print(f"[hexdata] ⚠️ 引用必附：{citation['attribution_text']}")


if __name__ == "__main__":
    main()
