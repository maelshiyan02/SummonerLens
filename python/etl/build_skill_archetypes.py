# -*- coding: utf-8 -*-
"""M1 · 生成英雄技能原型标注表（v2：可追溯底稿 + 人工校订合并）。

v1 缺陷（已修）：
  1. 把**技能名**纳入匹配 -> "逆流投掷"误报 range、技能名"冲锋"误报 mobility。
  2. **否定语境**误判 -> "免疫减速/免疫控制/无法使用位移技能" 被当成具备该能力。
  3. `range` 由文本关键词决定（"投掷/射击"）而非普攻射程。
  4. 泛词误报 -> "消耗(怒气)" -> poke、"额外伤害" -> burst。
  5. 无证据、无校订位。

v2 做法：
  - 只匹配**技能描述**（不含技能名）；逐句做**否定语境剔除**。
  - `range` 仅由普攻射程(>=300)判定；另记 `has_ranged_skill`（存在远程技能）。
  - 每个标签输出**技能级证据**（P/Q/W/E/R）。
  - 读取 `archetype_overrides.json`（人工校订）合并为 `manual_tags`。

标签集：mobility / cc / sustain / aoe / burst / range / poke
  注：`cc` 采用**广义控制**（含减速·沉默等软控），硬控见 evidence 明细。

用法：
  python python/etl/build_skill_archetypes.py [version]

输出：data/meta/<version>/skill_archetypes.csv
  championId,key,name,title,ddragon_tags,ranged,attackrange,hp,
  auto_tags,auto_evidence,has_ranged_skill,manual_tags,manual_evidence,review_status
"""
import csv
import json
import re
import sys
from pathlib import Path

# 硬控（决定 cc 的核心）
HARD_CC = ["眩晕", "晕眩", "击飞", "击退", "压制", "魅惑", "嘲讽", "恐惧", "变形",
           "昏睡", "禁锢", "束缚", "定身", "石化", "缠绕", "沉没", "击晕", "眩晕"]
SOFT_CC = ["减速", "沉默", "致盲"]
MOBILITY = ["位移", "冲刺", "突进", "跳跃", "闪现", "翻滚", "传送", "瞬移", "冲锋", "滑步", "穿越地形"]
SUSTAIN = ["治疗", "回复", "护盾", "吸血", "生命偷取", "恢复生命", "回血", "生命值回复"]
AOE = ["范围", "圆形", "锥形", "直线", "区域", "群体", "周围", "扇形", "弹射", "波及"]
BURST = ["处决", "斩杀", "真实伤害", "爆发", "暴击"]
POKE = ["远程消耗", "poke"]
# 远程技能特征词（辅助列 has_ranged_skill：近战英雄是否有远程手段）
RANGED_SKILL_KW = ["弹道", "投掷", "射击", "投射", "飞弹", "箭矢", "火球", "炮弹", "远程", "法术弹"]

KEYWORDS = {
    "cc": HARD_CC + SOFT_CC,
    "mobility": MOBILITY,
    "sustain": SUSTAIN,
    "aoe": AOE,
    "burst": BURST,
    "poke": POKE,
}

# 否定语境：否定词后 14 个字符内的关键词不算命中
NEG_RE = re.compile(r"(免疫|不会|无法|不受|不再|不能|免于|移除|驱散|无效|抵抗)")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def latest_version(meta_dir: Path) -> str:
    vers = sorted([p.name for p in meta_dir.iterdir() if p.is_dir()], reverse=True)
    if not vers:
        raise SystemExit("未找到任何版本快照，请先运行 fetch_datadragon.py")
    return vers[0]


def split_sentences(text: str):
    """按句末标点与 <br> 切句。"""
    text = text.replace("<br>", "。").replace("<br/>", "。").replace("<br />", "。")
    parts = re.split(r"[。；;!！?\n]", text)
    return [p for p in parts if p.strip()]


def hit_tags(desc: str):
    """在单个技能描述里找标签（含否定剔除）。返回 {tag: [keyword,...]}"""
    tags = {}
    for sent in split_sentences(desc):
        for tag, kws in KEYWORDS.items():
            for kw in kws:
                idx = sent.find(kw)
                if idx < 0:
                    continue
                # 否定剔除：关键词前 14 字符内有否定词则跳过
                pre = sent[max(0, idx - 14):idx]
                if NEG_RE.search(pre):
                    continue
                tags.setdefault(tag, set()).add(kw)
    return {t: sorted(v) for t, v in tags.items()}


def main() -> None:
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    meta = project_root() / "data" / "meta"
    ver = ver or latest_version(meta)
    base = meta / ver
    full = json.loads((base / "champions_full.json").read_text(encoding="utf-8"))

    ov_path = base / "archetype_overrides.json"
    overrides = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}

    rows = []
    for cid, c in sorted(full.items(), key=lambda kv: int(kv[1]["key"])):
        # 以「技能单元」组织：P / Q / W / E / R
        units = [("P", c.get("passive", {}).get("description", ""))]
        slot = ["Q", "W", "E", "R"]
        for i, s in enumerate(c.get("spells", [])):
            units.append((slot[i] if i < len(slot) else f"S{i}", s.get("description", "")))

        tag_ev = {}          # tag -> [slot,...]
        tag_kw = {}          # tag -> set(keyword)
        for slot_name, desc in units:
            for t, kws in hit_tags(desc).items():
                tag_ev.setdefault(t, []).append(slot_name)
                tag_kw.setdefault(t, set()).update(kws)

        attack_range = c.get("stats", {}).get("attackrange", 0)
        ranged = "远程" if attack_range and attack_range >= 300 else "近战"
        if ranged == "远程":
            tag_ev.setdefault("range", []).append("AA")
            tag_kw.setdefault("range", set()).add("普攻射程")

        auto_tags = sorted(tag_ev.keys())
        evidence = " | ".join(
            f"{t}:[{','.join(sorted(set(tag_ev[t])))}]<-{','.join(sorted(tag_kw[t]))}"
            for t in auto_tags)
        has_ranged_skill = any(kw in desc for _s, desc in units for kw in RANGED_SKILL_KW)

        rows.append({
            "championId": cid,
            "key": c["key"],
            "name": c["name"],
            "title": c.get("title", ""),
            "ddragon_tags": "|".join(c.get("tags", [])),
            "ranged": ranged,
            "attackrange": attack_range,
            "hp": c.get("stats", {}).get("hp", ""),
            "auto_tags": "|".join(auto_tags),
            "auto_evidence": evidence,
            "has_ranged_skill": has_ranged_skill,
            "manual_tags": "",
            "manual_evidence": "",
            "review_status": "",
        })

    # 合并人工校订（无 override 时 manual_tags 回退为 auto_tags）
    for r in rows:
        ov = overrides.get(r["championId"])
        if ov is not None:
            r["manual_tags"] = "|".join(ov.get("tags", []))
            r["manual_evidence"] = ov.get("note", "")
            r["review_status"] = ov.get("status", "reviewed")
        else:
            r["manual_tags"] = r["auto_tags"]
            r["manual_evidence"] = ""
            r["review_status"] = "auto"

    out = base / "skill_archetypes.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[archetype] v2 写出 {len(rows)} 行 -> {out}（人工校订 {sum(1 for r in rows if r['review_status'])} 行）")


if __name__ == "__main__":
    main()
