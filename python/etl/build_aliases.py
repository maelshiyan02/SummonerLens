# -*- coding: utf-8 -*-
"""M1 · 建英雄别名词典（中文刚需：如「快乐风男」→亚索）。

来源：
  1. Data Dragon 的英雄 name / title（自由使用）——基础别名。
  2. hexdata 的 /data/ai-summary.json 中的 heroAliases（**检索式获取 allowed**，
     独立训练/批量转载/商用 disallowed）。取用时**落 citation 文件**
     （source_url + buildId + reportPatch + reportDate），遵守 A02 边界。
     抓取失败则降级为仅 Data Dragon，不报错。

输出：
  data/meta/<version>/aliases.csv            英雄别名表
  data/meta/<version>/hexdata_citation.json  引用溯源（若能取到）
"""
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

HEXDATA_AI = "https://hexdata.com.cn/data/ai-summary.json"
UA = "SummonerLens/0.1 (+alias etl; maelshiyan02)"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def latest_version(meta_dir: Path) -> str:
    vers = sorted([p.name for p in meta_dir.iterdir() if p.is_dir()], reverse=True)
    if not vers:
        raise SystemExit("未找到版本快照，请先运行 fetch_datadragon.py")
    return vers[0]


def try_hexdata():
    """用 curl 取 hexdata ai-summary.json（检索式获取 allowed）；失败则降级。"""
    try:
        out = subprocess.run(
            ["curl", "-sSL", "--max-time", "45", "-H", f"User-Agent: {UA}", HEXDATA_AI],
            capture_output=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            return json.loads(out.stdout.decode("utf-8")), None
        return None, (out.stderr.decode("utf-8", "ignore")[:160] or "curl 返回空")
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def main() -> None:
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    meta = project_root() / "data" / "meta"
    ver = ver or latest_version(meta)
    base = meta / ver

    champ_list = json.loads((base / "raw" / "champion.json").read_text(encoding="utf-8"))
    champs = champ_list["data"]
    by_key = {c["key"]: c for c in champs.values()}

    # hexdata 别名（可选）
    hx_aliases = {}
    hx, err = try_hexdata()
    if hx:
        (base / "raw" / "hexdata-ai-summary.json").write_text(
            json.dumps(hx, ensure_ascii=False, indent=2), encoding="utf-8")
        raw_aliases = hx.get("heroAliases") or []
        # 兼容三种结构：list[{id,name,alternateNames}] / {key:[...]} / {key:str}
        if isinstance(raw_aliases, dict):
            for k, v in raw_aliases.items():
                hx_aliases[str(k)] = v if isinstance(v, list) else [str(v)]
        elif isinstance(raw_aliases, list):
            for item in raw_aliases:
                if isinstance(item, dict):
                    key = str(item.get("id", ""))
                    alts = item.get("alternateNames") or item.get("aliases") or []
                    if not isinstance(alts, list):
                        alts = [str(alts)]
                    hx_aliases[key] = [str(a) for a in alts]
        citation = {
            "source": "Hexdata",
            "source_url": "https://hexdata.com.cn/data/ai-summary.json",
            "canonical": "https://hexdata.com.cn/",
            "buildId": hx.get("buildId", ""),
            "reportPatch": hx.get("reportPatch", ""),
            "reportDate": hx.get("reportDate", ""),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "usage_note": "检索式获取 allowed；独立训练/批量转载/商用 disallowed；引用须附来源链接+buildId+reportPatch+reportDate",
        }
        (base / "hexdata_citation.json").write_text(
            json.dumps(citation, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[alias] hexdata heroAliases = {len(hx_aliases)} 条（已落 citation）")
    else:
        print(f"[alias] hexdata 抓取失败，降级为仅 Data Dragon（{err}）")

    out = base / "aliases.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["championId", "key", "name", "title", "aliases", "sources"])
        for cid, c in sorted(champs.items(), key=lambda kv: int(kv[1]["key"])):
            key = c["key"]
            base_aliases = [c["name"], c["title"]]
            extra = hx_aliases.get(key, [])
            aliases = base_aliases + [a for a in extra if a not in base_aliases]
            srcs = ["DataDragon"] + (["Hexdata"] if extra else [])
            w.writerow([cid, key, c["name"], c["title"], "|".join(aliases), "+".join(srcs)])
    print(f"[alias] 写出 {len(champs)} 行 -> {out}")


if __name__ == "__main__":
    main()
