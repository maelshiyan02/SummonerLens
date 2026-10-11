# -*- coding: utf-8 -*-
"""M1 · Data Dragon 全量抓取（英雄 + 装备），建版本快照。

用法：
  python python/etl/fetch_datadragon.py            # 抓最新版本
  python python/etl/fetch_datadragon.py 16.20.1    # 抓指定版本

输出（相对项目根）：
  data/meta/<version>/raw/{versions.json, champion.json, items.json, champions/<id>.json}
  data/meta/<version>/champions.csv          英雄基础表
  data/meta/<version>/champions_full.json    英雄完整数据（含技能/被动）
  data/meta/<version>/items.csv              装备表
  data/meta/<version>/snapshot.json          版本快照元信息

设计纪律：
  - 项目根**由脚本自身位置推导**（python/etl/xxx.py -> parents[2]），不写绝对路径。
  - 只依赖 Python 标准库，免 venv。
  - 元数据主源 = Riot Data Dragon（自由使用）。
"""
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DD = "https://ddragon.leagueoflegends.com"
LOCALE = "zh_CN"
UA = "SummonerLens/0.1 (+data-dragon etl; maelshiyan02)"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """优先 curl（本机走系统/代理 CA，规避 Python 标准库证书链问题），回退 urllib。"""
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


def get_json(url: str, retries: int = 3, timeout: int = 60):
    last = None
    for i in range(retries):
        try:
            return json.loads(_fetch_bytes(url, timeout).decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def main() -> None:
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    versions = get_json(f"{DD}/api/versions.json")
    if ver is None:
        ver = versions[0]
    print(f"[DD] 目标版本 = {ver}")

    base = project_root() / "data" / "meta" / ver
    raw = base / "raw"
    (raw / "champions").mkdir(parents=True, exist_ok=True)

    (raw / "versions.json").write_text(
        json.dumps(versions, ensure_ascii=False, indent=2), encoding="utf-8")

    # 英雄列表
    champ_list = get_json(f"{DD}/cdn/{ver}/data/{LOCALE}/champion.json")
    (raw / "champion.json").write_text(
        json.dumps(champ_list, ensure_ascii=False, indent=2), encoding="utf-8")
    champs = champ_list["data"]
    print(f"[DD] 英雄数 = {len(champs)}")

    # 装备
    items = get_json(f"{DD}/cdn/{ver}/data/{LOCALE}/item.json")
    (raw / "items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DD] 装备数 = {len(items['data'])}")

    # 英雄详情（逐个抓，含技能/被动）
    full = {}
    ordered = sorted(champs.items())
    for i, (cid, _c) in enumerate(ordered, 1):
        detail = get_json(f"{DD}/cdn/{ver}/data/{LOCALE}/champion/{cid}.json")
        full[cid] = detail["data"][cid]
        (raw / "champions" / f"{cid}.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
        if i % 20 == 0 or i == len(ordered):
            print(f"  ... 英雄详情 {i}/{len(ordered)}")
        time.sleep(0.05)

    (base / "champions_full.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")

    # 英雄基础表
    with (base / "champions.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "key", "name", "title", "tags", "partype", "hp", "hpperlevel",
                    "armor", "attackrange", "movespeed", "difficulty", "attack", "magic", "toughness"])
        for cid, c in sorted(champs.items(), key=lambda kv: int(kv[1]["key"])):
            st = c.get("stats", {})
            info = c.get("info", {})
            w.writerow([c["id"], c["key"], c["name"], c["title"], "|".join(c.get("tags", [])),
                        c.get("partype", ""), st.get("hp", ""), st.get("hpperlevel", ""),
                        st.get("armor", ""), st.get("attackrange", ""), st.get("movespeed", ""),
                        info.get("difficulty", ""), info.get("attack", ""), info.get("magic", ""),
                        info.get("toughness", "")])

    # 装备表
    with (base / "items.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "gold_total", "gold_base", "gold_sell", "purchasable",
                    "tags", "stats", "into", "from", "description"])
        for iid, it in sorted(items["data"].items(), key=lambda kv: int(kv[0])):
            g = it.get("gold", {})
            w.writerow([iid, it.get("name", ""), g.get("total", ""), g.get("base", ""), g.get("sell", ""),
                        it.get("purchasable", ""), "|".join(it.get("tags", [])),
                        json.dumps(it.get("stats", {}), ensure_ascii=False),
                        "|".join(it.get("into", [])), "|".join(it.get("from", [])),
                        (it.get("description", "") or "").replace("\n", " ")[:300]])

    # 快照元信息
    snap = {
        "version": ver,
        "locale": LOCALE,
        "champion_count": len(champs),
        "item_count": len(items["data"]),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "Riot Data Dragon",
        "source_url": f"{DD}/cdn/{ver}/data/{LOCALE}/champion.json",
        "dd_versions_head": versions[:5],
    }
    (base / "snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DD] 完成 -> {base}")


if __name__ == "__main__":
    main()
