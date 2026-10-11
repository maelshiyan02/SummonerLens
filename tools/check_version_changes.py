# -*- coding: utf-8 -*-
"""M1 · 版本变更检测：比较两个 Data Dragon 版本快照，输出英雄/装备变更。

用法：
  python tools/check_version_changes.py               # 比较最新两个版本
  python tools/check_version_changes.py <old> <new>   # 指定版本
  python tools/check_version_changes.py --list        # 列出已有快照

判据（仅一行一个结论，便于反向验证）：
  - 新增英雄 / 被移除英雄
  - 新增装备 / 被移除装备
  - 英雄技能文本或基础数值发生变化（用于追踪"机制与数值常改"）
"""
import json
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def list_versions(meta: Path):
    return sorted([p.name for p in meta.iterdir() if p.is_dir()], reverse=True)


def champ_sig(c: dict) -> dict:
    """提取用于变更比对的英雄签名（技能文本 + 关键基础数值）。"""
    sig = {
        "stats": c.get("stats", {}),
        "passive": c.get("passive", {}).get("description", ""),
    }
    for s in c.get("spells", []):
        sig[s.get("id", s.get("name", "?"))] = {
            "name": s.get("name", ""),
            "desc": s.get("description", ""),
            "cd": s.get("cooldown", []),
            "cost": s.get("cost", []),
        }
    return sig


def load(base: Path, name: str):
    p = base / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    args = [a for a in sys.argv[1:]]
    meta = project_root() / "data" / "meta"
    vers = list_versions(meta)

    if "--list" in args:
        print("已有快照：", ", ".join(vers) if vers else "（无）")
        return
    if len(vers) < 2 and len(args) < 2:
        print(f"仅有 {len(vers)} 个快照（{vers}），无法比对。请先抓取第二个版本。")
        return

    old, new = (args[0], args[1]) if len(args) >= 2 else (vers[1], vers[0])
    b_old, b_new = meta / old, meta / new
    print(f"比较：{old} -> {new}")

    ch_old = load(b_old, "champions_full.json") or {}
    ch_new = load(b_new, "champions_full.json") or {}
    hp_old = load(b_old, "raw/items.json") or {"data": {}}
    hp_new = load(b_new, "raw/items.json") or {"data": {}}

    added_c = set(ch_new) - set(ch_old)
    removed_c = set(ch_old) - set(ch_new)
    changed_c = []
    for cid in sorted(set(ch_old) & set(ch_new)):
        if champ_sig(ch_old[cid]) != champ_sig(ch_new[cid]):
            changed_c.append(cid)

    it_old = set(hp_old.get("data", {}))
    it_new = set(hp_new.get("data", {}))
    added_i = it_new - it_old
    removed_i = it_old - it_new

    def show(title, items, names):
        if items:
            print(f"{title}（{len(items)}）：")
            for x in sorted(items):
                print(f"  - {x} {names.get(x, '')}")

    show("新增英雄", added_c, {k: v.get("name", "") for k, v in ch_new.items()})
    show("移除英雄", removed_c, {k: v.get("name", "") for k, v in ch_old.items()})
    show("新增装备", added_i, {k: v.get("name", "") for k, v in hp_new.get("data", {}).items()})
    show("移除装备", removed_i, {k: v.get("name", "") for k, v in hp_old.get("data", {}).items()})
    if changed_c:
        print(f"英雄机制/数值变化（{len(changed_c)}）：")
        for cid in changed_c:
            print(f"  - {cid} {ch_new[cid].get('name', '')}")
    if not (added_c or removed_c or added_i or removed_i or changed_c):
        print("无变更（英雄与装备签名一致）。")


if __name__ == "__main__":
    main()
