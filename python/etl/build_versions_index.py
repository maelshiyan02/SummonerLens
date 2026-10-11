# -*- coding: utf-8 -*-
"""M5 · 版本快照注册表：扫描 data/meta 与 data/agg，生成 data/versions.json。

为什么需要它：M5 起「版本」成为一等维度，前端与跨版本内核不应各自去猜目录结构；
本脚本把磁盘上的全部快照汇总成**唯一一份**注册表（随仓），供下游只读消费。

用法：
  python python/etl/build_versions_index.py            # 生成/刷新注册表（幂等）
  python python/etl/build_versions_index.py --check    # 只校验注册表与磁盘是否一致（CI 用）
  python python/etl/build_versions_index.py --print    # 打印到 stdout，不写文件

输出：data/versions.json
  schema        summonerlens.versions.v1
  latest        {meta, agg}  当前最新快照 id
  counts        {meta, agg}  快照数量
  warnings[]    扫描中发现的问题（目录名异常 / 元数据缺失或损坏）
  snapshots[]   kind, id, patch, patch_family, report_date, collected_at,
                path, is_latest, source, extra{...}

设计纪律：
  - 只依赖标准库；项目根由脚本自身位置推导（python/etl/xxx.py -> parents[2]）。
  - **幂等**：内容未变化时不重写文件，避免 generated_at 造成 git 噪声。
  - **不静默**：任何缺失/损坏的元数据都进 warnings，`--check` 下视为不一致并退出 1。
  - patch 命名空间不同（meta=Data Dragon 语义版本 16.20.1；agg=hexdata reportPatch 16.19），
    故额外提供 patch_family（主次版本，如 16.19）用于跨类关联。
"""
import csv
import json
import re
import sys
import time
from pathlib import Path

SCHEMA = "summonerlens.versions.v1"
VER_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
CSV_KEYS = ("locale", "champion_count", "item_count")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path):
    """返回 dict；缺失返回 None；解析失败返回 {'__error__': ...}。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        return {"__error__": f"{type(e).__name__}: {e}"}


def _ver_key(v: str):
    parts = []
    for x in str(v).split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def patch_family(patch):
    if not patch:
        return None
    parts = str(patch).split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(patch)


def _count_rows(p: Path):
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8-sig") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:  # noqa: BLE001
        return None


def scan_meta(root: Path):
    """扫描 data/meta/<ver>/ → (snapshots, warnings)。"""
    out, warnings = [], []
    base = root / "data" / "meta"
    if not base.is_dir():
        return out, ["data/meta 目录不存在"]
    dirs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: _ver_key(p.name))
    for d in dirs:
        if not VER_RE.match(d.name):
            warnings.append(f"meta/{d.name} 目录名不是版本号，已跳过")
            continue
        snap = _load_json(d / "snapshot.json")
        if snap is None:
            warnings.append(f"meta/{d.name} 缺 snapshot.json")
            snap = {}
        elif "__error__" in snap:
            warnings.append(f"meta/{d.name}/snapshot.json 解析失败：{snap['__error__']}")
            snap = {}
        ver = snap.get("version") or d.name
        out.append({
            "kind": "meta",
            "id": d.name,
            "patch": ver,
            "patch_family": patch_family(ver),
            "report_date": None,          # Data Dragon 无「报告日期」概念
            "collected_at": snap.get("fetched_at"),
            "path": f"data/meta/{d.name}",
            "source": snap.get("source"),
            "extra": {k: snap.get(k) for k in CSV_KEYS if snap.get(k) is not None},
        })
    return out, warnings


def scan_agg(root: Path):
    """扫描 data/agg/<buildId>/ → (snapshots, warnings)。"""
    out, warnings = [], []
    base = root / "data" / "agg"
    if not base.is_dir():
        return out, ["data/agg 目录不存在"]
    for d in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name):
        cit = _load_json(d / "citation.json")
        if cit is None:
            warnings.append(f"agg/{d.name} 缺 citation.json")
            cit = {}
        elif "__error__" in cit:
            warnings.append(f"agg/{d.name}/citation.json 解析失败：{cit['__error__']}")
            cit = {}
        patch = cit.get("reportPatch")
        out.append({
            "kind": "agg",
            "id": d.name,
            "patch": patch,
            "patch_family": patch_family(patch),
            "report_date": cit.get("reportDate"),
            "collected_at": cit.get("fetched_at"),
            "path": f"data/agg/{d.name}",
            "source": cit.get("source"),
            "extra": {
                "hero_rows": _count_rows(d / "top_heroes.csv"),
                "augment_rows": _count_rows(d / "top_augments.csv"),
                "attribution_text": cit.get("attribution_text"),
            },
        })
    return out, warnings


def build(root: Path) -> dict:
    """构建注册表文档（不含 generated_at，便于比较）。"""
    meta, w1 = scan_meta(root)
    agg, w2 = scan_agg(root)

    latest_meta = max((m["id"] for m in meta), key=_ver_key) if meta else None
    latest_file = root / "data" / "agg" / "LATEST"
    if latest_file.exists():
        latest_agg = latest_file.read_text(encoding="utf-8").strip()
    else:
        latest_agg = agg[-1]["id"] if agg else None

    for s in meta:
        s["is_latest"] = (s["id"] == latest_meta)
    for s in agg:
        s["is_latest"] = (s["id"] == latest_agg)

    snapshots = sorted(
        meta + agg,
        key=lambda s: (s["kind"], _ver_key(s["id"]) if s["kind"] == "meta" else s["id"]),
    )
    return {
        "schema": SCHEMA,
        "latest": {"meta": latest_meta, "agg": latest_agg},
        "counts": {"meta": len(meta), "agg": len(agg)},
        "warnings": w1 + w2,
        "snapshots": snapshots,
    }


def _body(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "generated_at"}


def write_doc(path: Path, doc: dict) -> bool:
    """内容未变化则不重写（幂等）。返回是否发生写盘。"""
    body = _body(doc)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if _body(old) == body:
                return False
        except Exception:  # noqa: BLE001
            pass
    final = {
        "schema": doc["schema"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "latest": doc["latest"],
        "counts": doc["counts"],
        "warnings": doc["warnings"],
        "snapshots": doc["snapshots"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def do_check(path: Path, doc: dict) -> int:
    if not path.exists():
        print(f"[versions] ❌ 注册表不存在：{path}（请先运行 build_versions_index.py）")
        return 1
    old = json.loads(path.read_text(encoding="utf-8"))
    new_body, old_body = _body(doc), _body(old)
    bad = False
    if old_body != new_body:
        bad = True
        print("[versions] ❌ 注册表与磁盘不一致：")
        for key in ("latest", "counts"):
            if old_body.get(key) != new_body.get(key):
                print(f"    - {key}: 文件={old_body.get(key)} 磁盘={new_body.get(key)}")
        o_ids = [s["id"] for s in old_body.get("snapshots", [])]
        n_ids = [s["id"] for s in new_body.get("snapshots", [])]
        if o_ids != n_ids:
            print(f"    - 快照集合: 文件={o_ids} 磁盘={n_ids}")
        elif old_body.get("snapshots") != new_body.get("snapshots"):
            print("    - 快照字段有变动（集合相同）")
    if doc["warnings"]:
        bad = True
        print(f"[versions] ❌ 扫描发现 {len(doc['warnings'])} 条问题：")
        for w in doc["warnings"]:
            print(f"    - {w}")
    if not bad:
        print(f"[versions] ✅ 注册表与磁盘一致（meta={doc['counts']['meta']} agg={doc['counts']['agg']}）")
        return 0
    return 1


def main() -> None:
    root = project_root()
    path = root / "data" / "versions.json"
    doc = build(root)
    args = sys.argv[1:]

    if "--print" in args:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return
    if "--check" in args:
        sys.exit(do_check(path, doc))

    changed = write_doc(path, doc)
    for w in doc["warnings"]:
        print(f"[versions] ⚠️ {w}")
    print(f"[versions] meta 快照={doc['counts']['meta']}  最新={doc['latest']['meta']}")
    print(f"[versions] agg  快照={doc['counts']['agg']}  最新={doc['latest']['agg']}")
    print(f"[versions] {'已更新' if changed else '内容未变化（保留原文件）'} -> {path}")


if __name__ == "__main__":
    main()
