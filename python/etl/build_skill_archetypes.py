# -*- coding: utf-8 -*-
"""M1 · 生成英雄技能原型标注表（首版自动打标，供人工校订）。

依据 Data Dragon 英雄详情：职业 tags + 普攻射程 + 技能文本关键词 → 原型标签。
输出 data/meta/<version>/skill_archetypes.csv

标签集：mobility / cc / sustain / aoe / burst / range / poke
说明：自动打标是"首版草稿"，人工校订后以人工为准（列 manual_* 预留给后续）。
"""
import csv
import json
import sys
from pathlib import Path

# 关键词 → 标签（可扩充）
KEYWORDS = {
    "mobility": ["位移", "冲刺", "突进", "跳跃", "闪现", "翻滚", "传送", "瞬移", "冲锋", "滑步"],
    "cc": ["眩晕", "击飞", "击退", "沉默", "减速", "束缚", "禁锢", "嘲讽", "恐惧", "变形",
           "昏睡", "压制", "定身", "魅惑", "晕眩"],
    "sustain": ["治疗", "回复", "护盾", "吸血", "生命偷取", "恢复", "回血"],
    "aoe": ["范围", "圆形", "锥形", "直线", "区域", "群体", "周围", "弹射", "扇形"],
    "burst": ["爆发", "额外伤害", "暴击", "处决", "斩杀", "真实伤害"],
    "range": ["远程", "弹道", "投掷", "射击", "射程", "法术弹", "投射"],
    "poke": ["消耗", "远程消耗", "poke"],
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def latest_version(meta_dir: Path) -> str:
    vers = sorted([p.name for p in meta_dir.iterdir() if p.is_dir()], reverse=True)
    if not vers:
        raise SystemExit("未找到任何版本快照，请先运行 fetch_datadragon.py")
    return vers[0]


def main() -> None:
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    meta = project_root() / "data" / "meta"
    ver = ver or latest_version(meta)
    base = meta / ver
    full = json.loads((base / "champions_full.json").read_text(encoding="utf-8"))

    rows = []
    for cid, c in sorted(full.items(), key=lambda kv: int(kv[1]["key"])):
        passive = c.get("passive", {})
        text = (passive.get("name", "") + passive.get("description", ""))
        for s in c.get("spells", []):
            text += s.get("name", "") + s.get("description", "")
        hits = {k for k, kws in KEYWORDS.items() if any(kw in text for kw in kws)}
        attack_range = c.get("stats", {}).get("attackrange", 0)
        ranged = "远程" if attack_range and attack_range >= 300 else "近战"
        if ranged == "远程":
            hits.add("range")
        rows.append({
            "championId": cid,
            "key": c["key"],
            "name": c["name"],
            "title": c.get("title", ""),
            "ddragon_tags": "|".join(c.get("tags", [])),
            "ranged": ranged,
            "attackrange": attack_range,
            "hp": c.get("stats", {}).get("hp", ""),
            "archetype_tags": "|".join(sorted(hits)),
            "manual_tags": "",   # 预留给人工校订
        })

    out = base / "skill_archetypes.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[archetype] 写出 {len(rows)} 行 -> {out}")


if __name__ == "__main__":
    main()
