# -*- coding: utf-8 -*-
"""M1 · 海克斯大乱斗（ARAM Mayhem）强化符文（Augment）元数据抓取与合成。

数据源 = CommunityDragon（latest，构建号见 content-metadata.json）：
  - game/maps/modespecificdata/kiwi.bin.json                    海克斯 augment 定义（Tra key / 图标 / 标签 / 平台ID）
  - plugins/rcp-be-lol-game-data/global/default/v1/augment-lists.json   各模式启用池（CHERRY / KIWI / KIWI_JADE）
  - plugins/rcp-be-lol-game-data/global/default/v1/cherry-augments.json 英文名 / 稀有度 / 图标
  - plugins/rcp-be-lol-game-data/global/zh_cn/v1/cherry-augments.json   中文名
  - game/{zh_cn,en_us}/data/menu/en_us/lol.stringtable.json       本地化文本（Tra key **转小写**后查 entries）
  - content-metadata.json                                        构建版本号

关键规则（务必记住）：
  - 模式代号：CHERRY=斗魂竞技场 · KIWI=海克斯大乱斗 · KIWI_JADE=海克斯(Jade变体)。
  - augment 的 NameTra/DescriptionTra 是**本地化 key**，展开方式 = key.lower() 查 stringtable["entries"]。
  - kiwi.bin.json 里除 augment 外还有非 dict 项，需过滤（只取 dict 且含 AugmentNameId）。

用法：
  python python/etl/fetch_augments.py            # 版本目录取 Data Dragon 最新快照目录（若有），否则 16.20.1
  python python/etl/fetch_augments.py 16.20.1    # 指定版本目录

输出（data/meta/<ddver>/）：
  raw/cdragon/{kiwi.bin.json, augment-lists.json, cherry-augments.json, cherry-augments.zh_cn.json,
               lol.stringtable.zh_cn.json, lol.stringtable.en_us.json, content-metadata.json}
  augments.csv            海克斯当前池 augment 表（中英名/描述/稀有度/标签/图标/池归属）
  augments_full.json      完整定义（池内 + 历史）
  augment_pools.json      各模式启用池
  （并更新 snapshot.json，追加 augments 段）

设计纪律：
  - 项目根**由脚本自身位置推导**（python/etl/xxx.py -> parents[2]），不写绝对路径。
  - 只依赖 Python 标准库，免 venv；抓取走 curl（本机 Python 证书链问题，见 A09）。
  - 大文件（kiwi.bin.json 12MB / stringtable 32MB）落 raw/（.gitignore 已排除），并做存在性缓存跳过。
"""
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CD = "https://raw.communitydragon.org/latest"
UA = "SummonerLens/0.1 (+augment etl; maelshiyan02)"

RARITY_ZH = {
    "kSilver": "银",
    "kGold": "金",
    "kPrismatic": "棱彩",
    "kEventChoice": "事件",
}

# (远端 URL, raw/cdragon 下的文件名)
SOURCES = [
    (f"{CD}/content-metadata.json", "content-metadata.json"),
    (f"{CD}/game/maps/modespecificdata/kiwi.bin.json", "kiwi.bin.json"),
    (f"{CD}/plugins/rcp-be-lol-game-data/global/default/v1/augment-lists.json", "augment-lists.json"),
    (f"{CD}/plugins/rcp-be-lol-game-data/global/default/v1/cherry-augments.json", "cherry-augments.en.json"),
    (f"{CD}/plugins/rcp-be-lol-game-data/global/zh_cn/v1/cherry-augments.json", "cherry-augments.zh_cn.json"),
    (f"{CD}/game/zh_cn/data/menu/en_us/lol.stringtable.json", "lol.stringtable.zh_cn.json"),
    (f"{CD}/game/en_us/data/menu/en_us/lol.stringtable.json", "lol.stringtable.en_us.json"),
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fetch_bytes(url: str, timeout: int = 180) -> bytes:
    """优先 curl（本机走系统/代理 CA，规避 Python 标准库证书链问题），回退 urllib。"""
    try:
        out = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout), "-H", f"User-Agent: {UA}", url],
            capture_output=True, timeout=timeout + 30)
        if out.returncode == 0 and out.stdout:
            return out.stdout
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_cached(url: str, dest: Path, min_bytes: int = 32) -> bytes:
    """下载到 dest（存在且 > min_bytes 则跳过，直接用缓存）。"""
    if dest.exists() and dest.stat().st_size > min_bytes:
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = _fetch_bytes(url)
    if len(data) <= min_bytes:
        raise RuntimeError(f"下载内容过小 {url} -> {len(data)}B")
    dest.write_bytes(data)
    return data


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def plain(rich: str) -> str:
    """把游戏富文本转纯文本：去 <tag>，<br> -> 空格，&nbsp; -> 空格。保留 @占位符@。"""
    if not rich:
        return ""
    import re
    t = rich.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return " ".join(t.split())


def main() -> None:
    root = project_root()
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    if ver is None:
        # 取 Data Dragon 已有快照目录里最新的一个，否则默认 16.20.1
        meta = root / "data" / "meta"
        cands = sorted([d.name for d in meta.iterdir() if d.is_dir()]) if meta.exists() else []
        ver = cands[-1] if cands else "16.20.1"
    base = root / "data" / "meta" / ver
    raw = base / "raw" / "cdragon"
    raw.mkdir(parents=True, exist_ok=True)
    print(f"[AUG] 目标版本目录 = data/meta/{ver}")

    # 1) 抓取（带缓存）
    for url, name in SOURCES:
        dst = raw / name
        before = dst.stat().st_size if dst.exists() else 0
        download_cached(url, dst)
        after = dst.stat().st_size
        flag = "(缓存)" if before == after else "(下载)"
        print(f"  {flag} {name:34s} {after:>10,}B")
    time.sleep(0.1)

    cd_meta = load_json(raw / "content-metadata.json")
    cd_build = cd_meta.get("version", "")
    print(f"[AUG] CommunityDragon build = {cd_build}")

    # 2) 载入
    zent = load_json(raw / "lol.stringtable.zh_cn.json")["entries"]
    eent = load_json(raw / "lol.stringtable.en_us.json")["entries"]
    kiwi = load_json(raw / "kiwi.bin.json")
    lists = load_json(raw / "augment-lists.json")
    ca_en = {x["augmentNameId"]: x for x in load_json(raw / "cherry-augments.en.json")}
    ca_zh = {x["augmentNameId"]: x for x in load_json(raw / "cherry-augments.zh_cn.json")}

    # 3) 模式池
    pools = {g["modeName"]: g["augmentList"] for g in lists}
    pool_names = {m: {p.rsplit("/", 1)[-1] for p in lst} for m, lst in pools.items()}
    print(f"[AUG] 模式池: " + " | ".join(f"{m}={len(s)}" for m, s in pool_names.items()))

    # 4) 合成
    defs = {k: v for k, v in kiwi.items() if isinstance(v, dict) and v.get("AugmentNameId")}
    look = lambda key, tab: tab.get((key or "").lower(), "")

    rows = []
    for path, v in defs.items():
        aid = v["AugmentNameId"]
        rarity = (ca_en.get(aid) or {}).get("rarity", "")
        ca = ca_zh.get(aid) or ca_en.get(aid) or {}
        icon = ca.get("augmentSmallIconPath", "") or v.get("AugmentSmallIconPath", "")
        rows.append({
            "augment_id": aid,
            "name_zh": look(v.get("NameTra"), zent) or (ca_zh.get(aid) or {}).get("nameTRA", ""),
            "name_en": look(v.get("NameTra"), eent) or (ca_en.get(aid) or {}).get("nameTRA", ""),
            "rarity": rarity,
            "rarity_zh": RARITY_ZH.get(rarity, rarity),
            "desc_zh": look(v.get("DescriptionTra"), zent),
            "desc_en": look(v.get("DescriptionTra"), eent),
            "display_tags": "|".join(str(t) for t in (v.get("AugmentDisplayTags") or [])),
            "platform_id": v.get("AugmentPlatformId", ""),
            "icon_small": icon,
            "root_spell": v.get("RootSpell", ""),
            "in_pool_kiwi": aid in pool_names.get("KIWI", set()),
            "in_pool_cherry": aid in pool_names.get("CHERRY", set()),
            "in_pool_kiwi_jade": aid in pool_names.get("KIWI_JADE", set()),
        })
    for r in rows:
        r["desc_zh_plain"] = plain(r["desc_zh"])

    # 排序：池内优先 -> 稀有度(金/棱彩/银) -> 名称
    order = {"kPrismatic": 0, "kGold": 1, "kSilver": 2, "kEventChoice": 3}
    rows.sort(key=lambda r: (not r["in_pool_kiwi"], order.get(r["rarity"], 9), r["name_zh"]))

    # 5) 落盘：augments.csv（全量，含池归属）
    cols = ["augment_id", "name_zh", "name_en", "rarity", "rarity_zh", "desc_zh", "desc_en",
            "desc_zh_plain", "display_tags", "platform_id", "icon_small", "root_spell",
            "in_pool_kiwi", "in_pool_cherry", "in_pool_kiwi_jade"]
    with (base / "augments.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # augments_full.json（完整字段，便于程序加载）
    (base / "augments_full.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # augment_pools.json
    (base / "augment_pools.json").write_text(json.dumps({
        "communitydragon_build": cd_build,
        "pools": {m: sorted(s) for m, s in pool_names.items()},
        "pool_sizes": {m: len(s) for m, s in pool_names.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # augment_display_tags.json —— 类别标签文本字典
    # 注意：AugmentDisplayTags 字段是**整型**枚举（如 [4]），其「数字 ↔ 名称」映射在游戏 UI 内部，
    #       未在公开数据中暴露 ⇒ 本文件只提供 11 个类别名的中英文本，数字映射待补。
    tag_prefix = "cherry_augmentdisplaytag_"
    tags = {
        k[len(tag_prefix):]: {"zh": zent[k], "en": eent.get(k, "")}
        for k in sorted(zent) if k.startswith(tag_prefix)
    }
    (base / "augment_display_tags.json").write_text(json.dumps({
        "note": "AugmentDisplayTags 为整型枚举；数字↔名称映射待补。下列为类别名文本（中/英）。",
        "tag_count": len(tags),
        "tags": tags,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) 更新 snapshot.json（追加 augments 段）
    snap_path = base / "snapshot.json"
    snap = load_json(snap_path) if snap_path.exists() else {"version": ver}
    pool_rows = [r for r in rows if r["in_pool_kiwi"]]
    from collections import Counter
    snap["augments"] = {
        "source": "CommunityDragon",
        "communitydragon_build": cd_build,
        "augment_defs_total": len(rows),
        "kiwi_pool_size": len(pool_rows),
        "cherry_pool_size": len(pool_names.get("CHERRY", set())),
        "kiwi_jade_pool_size": len(pool_names.get("KIWI_JADE", set())),
        "kiwi_pool_rarity": dict(Counter(r["rarity"] for r in pool_rows)),
        "name_hit_zh": sum(1 for r in pool_rows if r["name_zh"]),
        "desc_hit_zh": sum(1 for r in pool_rows if r["desc_zh"]),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    snap_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    # 7) 断言（缺名/缺描述即 FAIL）
    miss_name = [r["augment_id"] for r in pool_rows if not r["name_zh"]]
    miss_desc = [r["augment_id"] for r in pool_rows if not r["desc_zh"]]
    if miss_name or miss_desc:
        raise SystemExit(f"断言失败：缺名 {miss_name[:5]} 缺描述 {miss_desc[:5]}")
    print(f"[AUG] 完成 -> {base}")
    print(f"[AUG] 池内 {len(pool_rows)} 条全部含中文名+描述；CSV={len(rows)} 行")


if __name__ == "__main__":
    main()
