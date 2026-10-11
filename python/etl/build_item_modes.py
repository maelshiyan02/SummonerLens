# -*- coding: utf-8 -*-
"""M1 · 装备模式归属（ARAM Mayhem / 海克斯大乱斗 装备核验）。

目的：核验「海克斯大乱斗（ARAM Mayhem）新增装备是否在标准 item.json 之外」，
并把每件装备的**模式归属**补进表里（Data Dragon 的 item.json 自带 `maps` 字段，
但既有 items.csv 把它丢掉了）。

事实结论（详见 .agent/memory/appendices/A12）：
  - DD item.json（870 件）已完整包含模式装备，**没有任何装备在 item.json 之外**；
  - ARAM Mayhem 跑在 **Map12 = 嚎哭深渊**，且**没有独立装备目录**（kiwi.bin.json 只有 Augment）；
  - 每件装备按 id 前缀存在**模式副本**：12xxxx=ARAM、66xxxx=召唤师峡谷、22/44xxxx=竞技场、77xxxx=Jade；
  - DD 的 `maps` 字段是**粗粒度**的（例：223084 心之钢 maps={12,30}），需辅以官方模式清单（jade-items.json）与 id 前缀判读。

用法：
  python python/etl/build_item_modes.py            # 用最新已抓版本（data/meta/ 下版本号最大者）
  python python/etl/build_item_modes.py 16.20.1

输出（相对项目根，data/meta/<version>/）：
  items_modes.csv            装备表（在原 items.csv 基础上扩展模式列）
  item_modes_summary.json    模式归属汇总（各 map 计数 / id 家族计数 / 一致性核验）
  aram_mayhem_items.json     海克斯大乱斗相关装备清单（含证据与置信度）

设计纪律：
  - 项目根**由脚本自身位置推导**（python/etl/xxx.py -> parents[2]），不写绝对路径。
  - 只依赖 Python 标准库；抓外部 JSON **curl 优先**（本机代理 CA 问题，见 A09）。
  - 原始 JSON 落 data/meta/<ver>/raw/cdragon/（.gitignore 排除）。
"""
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CD = "https://raw.communitydragon.org/latest"
UA = "SummonerLens/0.1 (+item-modes etl; maelshiyan02)"

# map id -> 可读模式名（Data Dragon maps 字段口径；见 A12）
MAP_NAMES = {
    "0": "Common", "11": "SR", "12": "ARAM", "22": "TFT",
    "30": "Arena", "453": "ClassicRift",
}

# 六位 id 前缀 -> 模式副本家族（实证，见 A12）
COPY_PREFIX = {
    "12": "aram_copy", "22": "arena_copy", "32": "copy_32",
    "44": "arena_copy_b", "55": "special_55", "66": "sr_copy",
    "77": "jade_copy", "99": "special_99",
}

# —— 海克斯大乱斗（ARAM Mayhem）相关装备（人工核验，附证据）——
# 证据：Riot 官方 Wiki (ARAM: Mayhem) / Riot 支持页 / 官方补丁说明 25.23·25.24
# 置信度：confirmed = 官方文档明确；mechanic/quest = 由游戏数据（kiwi.bin 任务）与 maps 推定
ARAM_MAYHEM = {
    # 官方 Wiki：ARAM: Mayhem 专属装备
    "1111":   {"en": "Jarvan I's",              "zh": "嘉文一世之靴", "scope": "exclusive", "confidence": "confirmed"},
    "3039":   {"en": "Atma's Reckoning",        "zh": "阿塔玛的清算", "scope": "exclusive", "confidence": "confirmed"},
    "123430": {"en": "Rite of Ruin",            "zh": "毁坏仪式",     "scope": "exclusive", "confidence": "confirmed"},
    "124011": {"en": "Sword of Blossoming Dawn","zh": "花晓之剑",     "scope": "exclusive", "confidence": "confirmed"},
    "994403": {"en": "Golden Spatula",          "zh": "金铲铲",       "scope": "exclusive", "confidence": "confirmed"},
    # 模式机制物（补丁 25.23 属性铁砧）
    "6032":   {"en": "Stat Bonus (Stat Anvil)", "zh": "属性加成",     "scope": "mode_mechanic", "confidence": "confirmed"},
    "220008": {"en": "Anvil Voucher",           "zh": "锻造器兑换券", "scope": "mode_mechanic", "confidence": "confirmed"},
    # augment 任务装备（kiwi.bin.json /ModesQuests：WoogletsWitchcap/VoidImmolation/UltraHydra/SteelYourHeart）
    "223069": {"en": "Void Immolation",         "zh": "虚空献祭",           "scope": "quest_item", "confidence": "high"},
    "223084": {"en": "Heartsteel",              "zh": "心之钢",             "scope": "quest_item", "confidence": "high"},
    "226668": {"en": "Ultra Hydra",             "zh": "终极九头蛇",         "scope": "quest_item", "confidence": "high"},
    "228002": {"en": "Wooglet's Witchcap",      "zh": "沃格勒特的巫师帽",   "scope": "quest_item", "confidence": "high"},
    # maps 恰为 {12} 但官方 Wiki 未明列 —— 待确认
    "4003":   {"en": "Lifeline",                "zh": "救生索",   "scope": "aram_only_pending", "confidence": "medium"},
    "4004":   {"en": "Spectral Cutlass",        "zh": "幽魂弯刀", "scope": "aram_only_pending", "confidence": "medium"},
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fetch_bytes(url: str, timeout: int = 90) -> bytes:
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


def get_json_cached(url: str, dest: Path, retries: int = 3) -> dict:
    """缓存优先：dest 存在且非空则直接读，否则抓取并落盘。"""
    if dest.exists() and dest.stat().st_size > 10:
        return json.loads(dest.read_text(encoding="utf-8"))
    last = None
    for i in range(retries):
        try:
            data = json.loads(_fetch_bytes(url).decode("utf-8"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def pick_version(root: Path) -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    metas = [p.name for p in (root / "data" / "meta").iterdir() if p.is_dir()]
    # 版本号形如 16.20.1，按数字段排序取最大
    def key(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return sorted(metas, key=key)[-1]


def id_family(iid: str) -> str:
    return COPY_PREFIX.get(iid[:2], f"copy_{iid[:2]}") if len(iid) == 6 else "base"


def main() -> None:
    root = project_root()
    ver = pick_version(root)
    base = root / "data" / "meta" / ver
    raw = base / "raw"
    cache = raw / "cdragon"
    cache.mkdir(parents=True, exist_ok=True)
    print(f"[item-modes] 版本 = {ver}")

    # 1) Data Dragon 原始 item.json（含 maps 字段）
    dd_raw = json.loads((raw / "items.json").read_text(encoding="utf-8"))["data"]

    # 2) CommunityDragon 富版 items.json（交叉核验）+ 中文/英文名
    cd_zh = {str(x["id"]): x for x in get_json_cached(
        f"{CD}/plugins/rcp-be-lol-game-data/global/zh_cn/v1/items.json",
        cache / "items.zh_cn.json")}
    cd_en = {str(x["id"]): x for x in get_json_cached(
        f"{CD}/plugins/rcp-be-lol-game-data/global/default/v1/items.json",
        cache / "items.default.json")}

    # 3) Jade 模式装备清单（官方按模式列举；map 453 = Classic Rift / Jade）
    jade_raw = get_json_cached(
        f"{CD}/plugins/rcp-be-lol-game-data/global/default/v1/jade-items.json",
        cache / "jade-items.json")
    jade_ids = {str(x["value"]["itemId"]) for x in jade_raw[0]["items"]}

    # 4) 一致性核验（DD vs CDragon）
    dd_ids, cd_ids = set(dd_raw), set(cd_zh)
    only_dd = sorted(dd_ids - cd_ids)
    only_cd = sorted(cd_ids - dd_ids)

    rows = []
    map_count = {}
    fam_count = {}
    for iid, it in dd_raw.items():
        maps = [k for k, v in (it.get("maps") or {}).items() if v]
        maps_sorted = sorted(maps, key=lambda x: int(x))
        modes = [MAP_NAMES.get(m, m) for m in maps_sorted]
        fam = id_family(iid)
        g = it.get("gold", {})
        name = it.get("name", "") or ""
        aram_meta = ARAM_MAYHEM.get(iid)
        row = {
            "id": iid,
            "name": name,
            "gold_total": g.get("total", ""),
            "gold_base": g.get("base", ""),
            "gold_sell": g.get("sell", ""),
            "purchasable": g.get("purchasable", ""),
            "maps": "|".join(maps_sorted),
            "modes": "|".join(modes),
            "id_family": fam,
            "in_jade_list": iid in jade_ids,
            "aram_mode": ("12" in maps_sorted and fam != "jade_copy"),
            "aram_mayhem_scope": (aram_meta or {}).get("scope", ""),
            "tags": "|".join(it.get("tags", [])),
            "stats": json.dumps(it.get("stats", {}), ensure_ascii=False),
            "into": "|".join(it.get("into", [])),
            "from": "|".join(it.get("from", [])),
            "name_en": cd_en.get(iid, {}).get("name", ""),
            "name_zh_cd": cd_zh.get(iid, {}).get("name", ""),
            "name_ok": bool(name) and not name.startswith(("Item_", "item_")),
            "description": (it.get("description", "") or "").replace("\n", " ")[:300],
        }
        rows.append(row)
        for m in maps_sorted:
            map_count[m] = map_count.get(m, 0) + 1
        fam_count[fam] = fam_count.get(fam, 0) + 1

    # 5) 写 items_modes.csv
    cols = ["id", "name", "name_en", "name_zh_cd", "name_ok",
            "gold_total", "gold_base", "gold_sell", "purchasable",
            "maps", "modes", "id_family", "in_jade_list", "aram_mode",
            "aram_mayhem_scope", "tags", "stats", "into", "from", "description"]
    rows.sort(key=lambda r: int(r["id"]))
    with (base / "items_modes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[item-modes] items_modes.csv 行数 = {len(rows)}")

    # 6) 汇总 + 一致性核验（断言：DD/CDragon 装备集必须完全一致）
    name_broken = [r["id"] for r in rows if not r["name_ok"]]
    aram_pool = [r["id"] for r in rows if r["aram_mode"]]
    summary = {
        "version": ver,
        "item_total": len(rows),
        "cross_check": {
            "dd_total": len(dd_ids),
            "cdragon_total": len(cd_ids),
            "only_in_dd": only_dd,
            "only_in_cdragon": only_cd,
            "identical": (not only_dd and not only_cd),
        },
        "map_coverage": {m: map_count[m] for m in sorted(map_count, key=lambda x: int(x))},
        "map_names": MAP_NAMES,
        "id_family_count": dict(sorted(fam_count.items())),
        "jade_list_size": len(jade_ids),
        "jade_all_77": all(i.startswith("77") for i in jade_ids),
        "name_broken": name_broken,
        "aram_pool_size": len(aram_pool),
        "aram_mayhem_exclusive_count": sum(1 for r in rows if r["aram_mayhem_scope"] == "exclusive"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "Riot Data Dragon + CommunityDragon",
    }
    (base / "item_modes_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 7) 海克斯大乱斗装备清单（含证据）
    aram_list = []
    for r in rows:
        if r["aram_mayhem_scope"]:
            meta = ARAM_MAYHEM[r["id"]]
            aram_list.append({
                "id": r["id"], "name_zh": r["name"], "name_en": r["name_en"],
                "scope": meta["scope"], "confidence": meta["confidence"],
                "gold_total": r["gold_total"], "maps": r["maps"],
            })
    aram_doc = {
        "version": ver,
        "gamemode": "ARAM: Mayhem / 海克斯大乱斗",
        "map_id": 12,
        "map_name": "Howling Abyss (嚎哭深渊)",
        "has_dedicated_item_catalog": False,
        "note": ("海克斯大乱斗无独立装备目录（kiwi.bin.json 仅含 Augment/任务），"
                 "沿用共享装备池；下列为其相关/专属装备。"),
        "evidence": [
            "Riot 官方 Wiki — ARAM: Mayhem（Items 章节列专属装备）",
            "Riot 支持页 — ARAM: Mayhem Game Mode",
            "官方补丁说明 25.23（Stat Anvil）/ 25.24（Hextech Gunblade, Sword of Blossoming Dawn）",
            "CommunityDragon game/maps/modespecificdata/kiwi.bin.json（Augment + /ModesQuests，均挂 Map12）",
        ],
        "exclusive": [x for x in aram_list if x["scope"] == "exclusive"],
        "mode_mechanic": [x for x in aram_list if x["scope"] == "mode_mechanic"],
        "quest_item": [x for x in aram_list if x["scope"] == "quest_item"],
        "pending": [x for x in aram_list if x["scope"] == "aram_only_pending"],
    }
    (base / "aram_mayhem_items.json").write_text(
        json.dumps(aram_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    # —— 关键断言（缺一即 FAIL）——
    assert summary["cross_check"]["identical"], "DD 与 CDragon 装备集不一致！"
    assert summary["jade_all_77"], "jade-items.json 出现非 77 系装备！"
    for i in ARAM_MAYHEM:
        assert i in dd_ids, f"海克斯专属装备 {i} 不在 item.json 中！"
    print("[item-modes] ✅ 一致性核验通过；海克斯专属全部在库")
    print(f"[item-modes] ARAM(map12) 池 = {len(aram_pool)}；"
          f"海克斯专属(confirmed) = {summary['aram_mayhem_exclusive_count']}")
    print(f"[item-modes] 占位名装备 = {name_broken}")
    print(f"[item-modes] 完成 -> {base}")


if __name__ == "__main__":
    main()
