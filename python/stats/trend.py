# -*- coding: utf-8 -*-
"""M5-2 · 跨版本对比内核（版本化维度）。

两类对比：
  diff_meta(from_ver, to_ver)   英雄 / 装备：新增 · 移除 · 机制数值变更
  diff_agg(from_bid, to_bid)    顶部英雄 / 符文：胜率与 pick 升降

契约（硬要求 · 承 kb M01「空结果判 FAIL」）：
  任一快照缺失、或同类快照不足 2 份 → 返回
      {"status": "insufficient_snapshots", "available": [...], "detail": "..."}
  **绝不以空列表冒充「无变化」**。CLI 下该状态退出码 = 3（预期 pending，非错误）。

快照清单来源：`data/versions.json`（由 python/etl/build_versions_index.py 生成）。
本模块**不自行扫描目录** —— 注册表是唯一真相。

CLI：
  python python/stats/trend.py list                 # 列出可用快照
  python python/stats/trend.py meta                 # 最新两版 meta 对比
  python python/stats/trend.py meta 16.19.1 16.20.1
  python python/stats/trend.py agg                  # 最新两份 agg 对比
  python python/stats/trend.py meta --json          # 机器可读输出
"""
import csv
import json
import sys
from pathlib import Path

PENDING_EXIT = 3  # insufficient_snapshots 的退出码（预期 pending，非失败）


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_index(root: Path) -> dict:
    p = root / "data" / "versions.json"
    if not p.exists():
        raise FileNotFoundError(
            f"缺少版本注册表 {p}；请先运行 python/etl/build_versions_index.py")
    return json.loads(p.read_text(encoding="utf-8"))


def snapshots_of(idx: dict, kind: str) -> list:
    return [s for s in idx.get("snapshots", []) if s.get("kind") == kind]


def _ver_key(v: str):
    out = []
    for x in str(v).split("."):
        try:
            out.append(int(x))
        except ValueError:
            out.append(-1)
    return tuple(out)


def _load_json(p: Path):
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _read_csv(p: Path):
    if not p.exists():
        return None
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _insufficient(kind: str, available: list, detail: str) -> dict:
    return {
        "status": "insufficient_snapshots",
        "kind": kind,
        "detail": detail,
        "available": available,
    }


# ---------------------------------------------------------------- meta diff

def _champ_sig(c: dict) -> dict:
    """英雄签名：基础数值 + 被动描述 + 各技能（文本/冷却/耗蓝/名称）。"""
    sig = {
        "stats": c.get("stats", {}),
        "passive": (c.get("passive") or {}).get("description", ""),
    }
    for s in (c.get("spells") or []):
        key = s.get("id") or s.get("name") or "?"
        sig[str(key)] = {
            "name": s.get("name", ""),
            "desc": s.get("description", ""),
            "cd": s.get("cooldown", []),
            "cost": s.get("cost", []),
        }
    return sig


def diff_meta(root: Path, from_ver: str, to_ver: str) -> dict:
    """两个 Data Dragon 版本快照的英雄/装备差异。"""
    base = root / "data" / "meta"
    d_from, d_to = base / from_ver, base / to_ver
    missing = [v for v, d in ((from_ver, d_from), (to_ver, d_to)) if not d.is_dir()]
    if missing:
        return _insufficient("meta", _list_ids(root, "meta"),
                             f"meta 快照不存在：{missing}")

    ch_from = _load_json(d_from / "champions_full.json")
    ch_to = _load_json(d_to / "champions_full.json")
    if not ch_from or not ch_to:
        return {"status": "error", "kind": "meta",
                "detail": f"champions_full.json 缺失或为空：{from_ver} / {to_ver}"}

    added = [{"id": k, "name": (ch_to[k] or {}).get("name", "")}
             for k in sorted(set(ch_to) - set(ch_from))]
    removed = [{"id": k, "name": (ch_from[k] or {}).get("name", "")}
               for k in sorted(set(ch_from) - set(ch_to))]

    changed = []
    for cid in sorted(set(ch_from) & set(ch_to)):
        a, b = _champ_sig(ch_from[cid] or {}), _champ_sig(ch_to[cid] or {})
        if a != b:
            fields = sorted(k for k in (set(a) | set(b)) if a.get(k) != b.get(k))
            changed.append({"id": cid, "name": (ch_to[cid] or {}).get("name", ""), "fields": fields})

    it_from = (_load_json(d_from / "raw" / "items.json") or {}).get("data", {})
    it_to = (_load_json(d_to / "raw" / "items.json") or {}).get("data", {})
    added_i = [{"id": k, "name": (it_to.get(k) or {}).get("name", "")}
               for k in sorted(set(it_to) - set(it_from))]
    removed_i = [{"id": k, "name": (it_from.get(k) or {}).get("name", "")}
                 for k in sorted(set(it_from) - set(it_to))]

    has_changes = bool(added or removed or changed or added_i or removed_i)
    return {
        "status": "ok",
        "kind": "meta",
        "from": from_ver,
        "to": to_ver,
        "champions": {"added": added, "removed": removed, "changed": changed},
        "items": {"added": added_i, "removed": removed_i},
        "summary": {
            "champions_added": len(added),
            "champions_removed": len(removed),
            "champions_changed": len(changed),
            "items_added": len(added_i),
            "items_removed": len(removed_i),
        },
        "has_changes": has_changes,
    }


# ----------------------------------------------------------------- agg diff

def _agg_moves(d_from: Path, d_to: Path, fname: str, limit: int = 5):
    rows_from = {r.get("id"): r for r in (_read_csv(d_from / fname) or []) if r.get("id")}
    rows_to = {r.get("id"): r for r in (_read_csv(d_to / fname) or []) if r.get("id")}
    common = sorted(set(rows_from) & set(rows_to))
    moves = []
    for k in common:
        w0, w1 = _num(rows_from[k].get("winRate")), _num(rows_to[k].get("winRate"))
        p0, p1 = _num(rows_from[k].get("pickRate")), _num(rows_to[k].get("pickRate"))
        if w0 is None or w1 is None:
            continue
        moves.append({
            "id": k,
            "name": rows_to[k].get("name", ""),
            "winRate_from": w0,
            "winRate_to": w1,
            "winRate_delta": round(w1 - w0, 6),
            "pickRate_from": p0,
            "pickRate_to": p1,
            "pickRate_delta": (round(p1 - p0, 6) if (p0 is not None and p1 is not None) else None),
        })
    rising = sorted(moves, key=lambda m: m["winRate_delta"], reverse=True)[:limit]
    falling = sorted(moves, key=lambda m: m["winRate_delta"])[:limit]
    return {
        "rows_from": len(rows_from),
        "rows_to": len(rows_to),
        "common": len(common),
        "only_in_from": sorted(set(rows_from) - set(rows_to)),
        "only_in_to": sorted(set(rows_to) - set(rows_from)),
        "rising": rising,
        "falling": falling,
    }


def diff_agg(root: Path, from_bid: str, to_bid: str) -> dict:
    """两个 hexdata buildId 快照的顶部英雄/符文升降。"""
    base = root / "data" / "agg"
    d_from, d_to = base / from_bid, base / to_bid
    missing = [b for b, d in ((from_bid, d_from), (to_bid, d_to)) if not d.is_dir()]
    if missing:
        return _insufficient("agg", _list_ids(root, "agg"),
                             f"agg 快照不存在：{missing}")

    heroes = _agg_moves(d_from, d_to, "top_heroes.csv")
    augments = _agg_moves(d_from, d_to, "top_augments.csv")
    if heroes["common"] == 0 and augments["common"] == 0:
        return _insufficient("agg", _list_ids(root, "agg"),
                             "两份 agg 快照没有可比对的共同实体（榜单口径可能已变）")

    return {
        "status": "ok",
        "kind": "agg",
        "from": from_bid,
        "to": to_bid,
        "heroes": heroes,
        "augments": augments,
        "has_changes": any(m["winRate_delta"] != 0
                           for m in (heroes["rising"] + heroes["falling"]
                                     + augments["rising"] + augments["falling"])),
    }


# --------------------------------------------------------------------- util

def _list_ids(root: Path, kind: str) -> list:
    try:
        idx = load_index(root)
    except FileNotFoundError:
        return []
    return [s["id"] for s in snapshots_of(idx, kind)]


def pick_latest_pair(root: Path, kind: str):
    """返回 (from, to) 或 None（不足 2 份）。meta 按版本升序，agg 按 id 升序。"""
    ids = _list_ids(root, kind)
    if len(ids) < 2:
        return None
    ids = sorted(ids, key=_ver_key) if kind == "meta" else sorted(ids)
    return ids[-2], ids[-1]


# ---------------------------------------------------------------------- CLI

def _print_meta(res: dict) -> None:
    if res["status"] != "ok":
        print(f"[trend] {res['status']}: {res.get('detail')}")
        if res.get("available"):
            print(f"[trend] 可用快照：{res['available']}")
        if res["status"] == "insufficient_snapshots" and res.get("kind") == "agg":
            print("[trend] 提示：聚合趋势需 ≥2 份 buildId 快照，靠定时抓取逐步积累。")
        return
    print(f"[trend] meta {res['from']} -> {res['to']}")
    s = res["summary"]
    print(f"[trend] 英雄：新增 {s['champions_added']} / 移除 {s['champions_removed']} / 变更 {s['champions_changed']}")
    print(f"[trend] 装备：新增 {s['items_added']} / 移除 {s['items_removed']}")
    for group, key in (("新增英雄", ("champions", "added")),
                       ("移除英雄", ("champions", "removed")),
                       ("新增装备", ("items", "added")),
                       ("移除装备", ("items", "removed"))):
        items = res[key[0]][key[1]]
        if items:
            print(f"[trend] {group}（{len(items)}）：")
            for it in items[:20]:
                print(f"    - {it['id']} {it['name']}")
    ch = res["champions"]["changed"]
    if ch:
        print(f"[trend] 英雄机制/数值变化（{len(ch)}）：")
        for it in ch[:30]:
            print(f"    - {it['id']} {it['name']}  改动字段: {', '.join(it['fields'])}")
    if not res["has_changes"]:
        print("[trend] 无变更（英雄与装备签名一致）。")


def _print_agg(res: dict) -> None:
    if res["status"] != "ok":
        print(f"[trend] {res['status']}: {res.get('detail')}")
        if res.get("available"):
            print(f"[trend] 可用快照：{res['available']}")
        print("[trend] 提示：聚合趋势需 ≥2 份 buildId 快照，靠定时抓取逐步积累。")
        return
    print(f"[trend] agg {res['from']} -> {res['to']}")
    for label, blk in (("英雄", res["heroes"]), ("符文", res["augments"])):
        print(f"[trend] {label}：可比对 {blk['common']} 个"
              f"（from {blk['rows_from']} 行 / to {blk['rows_to']} 行）")
        for tag, key in (("上升", "rising"), ("下降", "falling")):
            for m in blk[key]:
                print(f"    {tag} {m['name'] or m['id']}: "
                      f"{m['winRate_from']:.4f} -> {m['winRate_to']:.4f} "
                      f"({m['winRate_delta']:+.4f})")


def main() -> None:
    root = project_root()
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)

    kind = args[0]
    if kind == "list":
        idx = load_index(root)
        for s in idx["snapshots"]:
            tag = " (latest)" if s["is_latest"] else ""
            print(f"  [{s['kind']}] {s['id']}  patch={s['patch']}{tag}")
        return

    if kind not in ("meta", "agg"):
        print(f"[trend] 未知类型：{kind}（可用 meta / agg / list）")
        sys.exit(2)

    if len(args) >= 3:
        a, b = args[1], args[2]
    else:
        pair = pick_latest_pair(root, kind)
        if pair is None:
            res = _insufficient(kind, _list_ids(root, kind),
                                f"{kind} 快照不足 2 份，无法比对")
            print(json.dumps(res, ensure_ascii=False, indent=2) if as_json else "", end="")
            if not as_json:
                _print_meta(res) if kind == "meta" else _print_agg(res)
            sys.exit(PENDING_EXIT)
        a, b = pair

    res = diff_meta(root, a, b) if kind == "meta" else diff_agg(root, a, b)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _print_meta(res) if kind == "meta" else _print_agg(res)

    if res["status"] == "insufficient_snapshots":
        sys.exit(PENDING_EXIT)
    if res["status"] != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
