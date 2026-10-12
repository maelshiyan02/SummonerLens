# -*- coding: utf-8 -*-
"""M4 · 可视化数据束构建（bridge）

把 M1~M3 的产物聚合成**单一 JSON**，供离线仪表板（app/web）与 Flutter 壳直接消费。
不引入新依赖：只用标准库 + 本项目 python/ 模块。

数据分区（**绝不混用**，见 A14 §5 合规纪律）：
  - real   ：hexdata 聚合真实数据（`data/agg/<buildId>/top_*.csv`，随仓提交）→ 12 英雄 / 12 Augment /
             172 英雄别名词典。kind = "real_aggregate"
  - fixture：M3 合成夹具统计（`data/derived/m3/synthetic/*.csv`，派生且 gitignore）→ 引擎校验用。
             kind = "synthetic_fixture"，前端必须显著标注，不得作为对外结论。

输出：`app/web/data/dashboard.json`（派生，.gitignore 排除；可由本脚本重建）。

纪律：
  - 项目根由脚本自身位置推导（parents[2]）。
  - 每份数据集带 `kind/source/confidence/asof`；真实数据另带 `buildId/reportPatch/reportDate/attribution`。
  - 空结果 = 明确 `kind="unavailable"`，不得静默留空（见 kb M01/M02）。
"""
import ast
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # python/
from stats import wilson  # noqa: E402
from stats import trend as trend_core  # noqa: E402

SCHEMA = "summonerlens.dashboard.v1"
BUNDLE_REL = Path("app") / "web" / "data" / "dashboard.json"
RANK_METHOD = wilson.METHOD_TIER_THEN_WILSON

ROLE_ZH = {"Fighter": "战士", "Tank": "坦克", "Mage": "法师", "Assassin": "刺客",
           "Marksman": "射手", "Support": "辅助"}


# ----------------------------------------------------------------------------- helpers
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def pick_version(root: Path) -> str:
    metas = [p.name for p in (root / "data" / "meta").iterdir() if p.is_dir()]

    def k(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return sorted(metas, key=k)[-1]


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _num(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_pylist(s):
    """hexdata 的 alternateNames 形如 \"['亚索', '快乐风男']\"（Python list 字面量）。"""
    if not s:
        return []
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        try:
            v = ast.literal_eval(s)
            return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]
        except (ValueError, SyntaxError):
            return []
    return [s]


def norm_alias(s: str) -> str:
    """别名词典归一化：去空白、小写（拼音/英文大小写不敏感）。"""
    return "".join(str(s).split()).lower()


# ----------------------------------------------------------------------------- 元数据索引
def load_hero_meta(root: Path, ver: Path) -> dict:
    """champions.csv + aliases.csv → {key:int -> {name,title,tags,roles,aliases:[...]}}"""
    champs = read_csv(root / "data" / "meta" / ver / "champions.csv")
    aliases = read_csv(root / "data" / "meta" / ver / "aliases.csv") if \
        (root / "data" / "meta" / ver / "aliases.csv").exists() else []
    out = {}
    for c in champs:
        key = int(c["key"])
        tags = [t for t in (c.get("tags") or "").split("|") if t]
        out[key] = {"key": key, "name": c.get("name") or c.get("id"),
                    "title": c.get("title") or "", "tags": tags,
                    "roles": [ROLE_ZH.get(t, t) for t in tags], "aliases": []}
    for a in aliases:
        key = int(a["key"])
        if key not in out:
            continue
        al = [x for x in (a.get("aliases") or "").split("|") if x]
        seen = set()
        for x in [out[key]["name"], a.get("name"), a.get("title")] + al:
            if x and x not in seen:
                seen.add(x)
                out[key]["aliases"].append(x)
    return out


def load_hexdata_alias_pool(root: Path) -> dict:
    """hexdata hero_aliases.csv → {key:int -> [alternateNames...]}（补充昵称来源）。"""
    agg = root / "data" / "agg"
    latest = agg / "LATEST"
    if not latest.exists():
        return {}
    pool = {}
    fp = agg / latest.read_text(encoding="utf-8").strip() / "hero_aliases.csv"
    if not fp.exists():
        return {}
    for r in read_csv(fp):
        pool[int(r["id"])] = parse_pylist(r.get("alternateNames"))
    return pool


def build_alias_index(hero_meta: dict, hex_pool: dict):
    """归一化别名 → 英雄数值 key。含全名/称号/昵称/hexdata 别名。"""
    index = {}
    for key, info in hero_meta.items():
        cand = set(info["aliases"]) | set(hex_pool.get(key, []))
        for x in cand:
            n = norm_alias(x)
            if n:
                index.setdefault(n, key)
    return index


def load_augment_meta(root: Path, ver: str) -> dict:
    rows = read_csv(root / "data" / "meta" / ver / "augments.csv")
    out = {}
    for r in rows:
        pid = r.get("platform_id")
        if pid:
            try:
                out[int(pid)] = {"name": r.get("name_zh") or r.get("augment_id"),
                                 "name_en": r.get("name_en"), "rarity": r.get("rarity_zh")}
            except ValueError:
                continue
    return out


def load_item_meta(root: Path, ver: str) -> dict:
    rows = read_csv(root / "data" / "meta" / ver / "items.csv")
    out = {}
    for r in rows:
        try:
            out[int(r["id"])] = {"name": r.get("name"), "gold": _num(r.get("gold_total"))}
        except (ValueError, TypeError):
            continue
    return out


# ----------------------------------------------------------------------------- M5 版本化维度
def load_versions(root: Path) -> dict:
    """读取版本注册表（M5-1 产物）。缺失时返回空壳（避免崩溃）。"""
    p = root / "data" / "versions.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"schema": None, "snapshots": [], "latest": {}, "counts": {"meta": 0, "agg": 0}}


def _ver_tuple(v: str):
    out = []
    for x in str(v).split("."):
        try:
            out.append(int(x))
        except ValueError:
            out.append(-1)
    return tuple(out)


def meta_ids_of(root: Path) -> list:
    idx = load_versions(root)
    ids = [s["id"] for s in idx.get("snapshots", []) if s.get("kind") == "meta"]
    return sorted(ids, key=_ver_tuple)


def agg_ids_of(root: Path) -> list:
    idx = load_versions(root)
    ids = [s["id"] for s in idx.get("snapshots", []) if s.get("kind") == "agg"]
    return sorted(ids)


def build_metas_embed(root: Path) -> dict:
    """把**全部** meta 版本的英雄字典嵌进 bundle，供前端离线切换名称/别名。
    结构：{ver: {heroes:[{key,name,title,roles,aliases}]}}。"""
    out = {}
    for v in meta_ids_of(root):
        adir = root / "data" / "meta" / v
        if not (adir / "champions.csv").exists():
            continue
        hm = load_hero_meta(root, v)
        out[v] = {"heroes": [
            {"key": k, "name": i["name"], "title": i["title"],
             "roles": i["roles"], "aliases": i["aliases"]}
            for k, i in sorted(hm.items())
        ]}
    return out


def build_version_changes(root: Path) -> list:
    """相邻 meta 版本两两 diff（真实数据）。返回 trend.diff_meta 结果列表。"""
    metas = meta_ids_of(root)
    out = []
    for i in range(1, len(metas)):
        try:
            res = trend_core.diff_meta(root, metas[i - 1], metas[i])
        except Exception as e:  # 单对异常不应拖垮整束
            res = {"status": "error", "kind": "meta", "from": metas[i - 1],
                   "to": metas[i], "detail": str(e)}
        out.append(res)
    return out


def _shift_date(date_str: str, days: int) -> str:
    try:
        from datetime import date, timedelta
        d = date.fromisoformat(date_str)
        return (d + timedelta(days=days)).isoformat()
    except (ValueError, TypeError):
        return date_str


def _synthesize_trend(real_build: dict, n: int = 3) -> list:
    """聚合快照不足 2 份时：依据单份真实数据合成**多 build 演示序列**。
    明确标注 synthetic_fixture，仅用于开发/验收图表机制，绝非真实趋势。"""
    import hashlib
    base = real_build.get("series", {})
    out = []
    base_date = real_build.get("report_date") or "2026-09-27"
    for i in range(n):
        series = {}
        for k, v in base.items():
            h = int(hashlib.md5(("%s-%d" % (k, i)).encode("utf-8")).hexdigest(), 16)
            delta = ((h % 6000) / 6000.0 - 0.3) * 0.1  # 确定性 ±0.03
            series[k] = round(max(0.30, min(0.80, v + delta)), 6)
        out.append({
            "id": "synthetic-trend-%d" % (i + 1),
            "patch": real_build.get("patch"),
            "report_date": _shift_date(base_date, 30 * i),
            "series": series,
            "synthetic": True,
        })
    return out


def build_aggregate_trend(root: Path) -> dict:
    """英雄胜率跨 build 序列。≥2 份 agg 快照 → real_aggregate；否则 → synthetic_fixture。"""
    agg = root / "data" / "agg"
    idx = load_versions(root)
    builds = []
    for s in [x for x in idx.get("snapshots", []) if x.get("kind") == "agg"]:
        adir = agg / s["id"]
        hp = adir / "top_heroes.csv"
        if not hp.exists():
            continue
        series = {int(r["id"]): float(r["winRate"]) for r in read_csv(hp)}
        builds.append({"id": s["id"], "patch": s.get("patch"),
                       "report_date": s.get("report_date"), "series": series})
    if len(builds) >= 2:
        return {"kind": "real_aggregate", "insufficient": False, "builds": builds,
                "current": len(builds)}
    if builds:
        synth = _synthesize_trend(builds[0])
        return {"kind": "synthetic_fixture", "insufficient": True,
                "reason": "agg 仅 1 份快照：依据单份真实数据合成演示序列，非真实趋势",
                "builds": synth, "current": 1}
    return {"kind": "unavailable", "insufficient": True,
            "reason": "无 agg 快照", "builds": [], "current": 0}


def load_risk_notes(root: Path) -> list:
    """hexdata methodology.json 的 riskNotes（已抓未展示维度，规划 M5-4 顺带接入）。"""
    mf = root / "data" / "agg"
    if not (mf / "LATEST").exists():
        return []
    adir = mf / (mf / "LATEST").read_text(encoding="utf-8").strip()
    mj = adir / "methodology.json"
    if not mj.exists():
        return []
    try:
        d = json.loads(mj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rn = d.get("riskNotes")
    return rn if isinstance(rn, list) else []


# ----------------------------------------------------------------------------- 本人对局（personal，次级佐证 · 详细对局模型）
def build_personal(root: Path) -> dict:
    """读 data/personal/matches.jsonl（fetch_lcu.py / fetch_wegame.py 产出的「详细对局」schema），
    聚成本人 ARAM 战绩摘要（伤害构成 / 金 / 视野 / 补刀 / 装备 / 符文 / 海克斯 / 双方队伍上下文）。

    兼容两种 schema：新（含 participants/teams 数组）与旧（扁平 self 字段），
    本人行由 self_puuid 在 participants 中定位。无数据 → kind='unavailable'。

    合规：来源/可信度来自采集行（source=wegame/lcu，confidence=secondary/primary），
    本人自采、隐藏战绩取不到，仅次级佐证（A02/A07）。
    """
    from collections import defaultdict, Counter
    fp = root / "data" / "personal" / "matches.jsonl"
    if not fp.exists() or fp.stat().st_size < 5:
        return {"kind": "unavailable",
                "reason": "暂无本人对局数据。运行 python/etl/fetch_lcu.py（英雄联盟客户端开着时）"
                          "或 fetch_wegame.py 采集后，本页自动填充。",
                "prov": {"kind": "unavailable", "source": None, "confidence": None,
                          "asof": None, "note": "本人自采，仅次级佐证"}}

    rows = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        return {"kind": "unavailable", "reason": "matches.jsonl 为空",
                "prov": {"kind": "unavailable", "source": None, "confidence": None,
                         "asof": None, "note": "本人自采，仅次级佐证"}}

    def _extract_self(row):
        """从一行取出本人 participant（新 schema）或兼容旧扁平 schema。"""
        parts = row.get("participants")
        if parts:
            sp = row.get("self_puuid")
            for p in parts:
                if sp and str(p.get("puuid")) == str(sp):
                    return p, parts, row.get("teams") or []
        # 旧扁平 schema 兼容
        pseudo = {
            "champion_id": row.get("champion_id"), "champion_name": row.get("champion_name"),
            "team_id": None, "win": row.get("win"), "kills": row.get("kills"),
            "deaths": row.get("deaths"), "assists": row.get("assists"),
            "damage_to_champions": row.get("damage_dealt"), "damage_taken": row.get("damage_taken"),
            "gold_earned": row.get("gold_earned"), "vision_score": row.get("vision_score"),
            "total_minions_killed": row.get("cs"), "neutral_minions_killed": 0,
            "items": row.get("items") or [], "augments": row.get("augments") or [],
        }
        return pseudo, None, None

    def _n(v):
        return v if isinstance(v, (int, float)) else None

    def _avg(vals):
        vs = [v for v in vals if isinstance(v, (int, float))]
        return sum(vs) / len(vs) if vs else None

    def _sum(vals):
        return sum(v for v in vals if isinstance(v, (int, float)))

    def _top_ids(ids, top=3):
        return [i for i, _ in Counter(x for x in ids if x).most_common(top)]

    matches = []
    for r in rows:
        me, parts, teams = _extract_self(r)
        cs = (_n(me.get("total_minions_killed")) or 0) + (_n(me.get("neutral_minions_killed")) or 0)
        dmg = _n(me.get("damage_to_champions")) or 0
        m = _n(me.get("magic_dmg_champ")) or 0
        p = _n(me.get("physical_dmg_champ")) or 0
        t = _n(me.get("true_dmg_champ")) or 0
        matches.append({
            "row": r, "me": me, "parts": parts, "teams": teams,
            "win": bool(me.get("win")),
            "kills": _n(me.get("kills")) or 0, "deaths": _n(me.get("deaths")) or 0,
            "assists": _n(me.get("assists")) or 0,
            "gold": _n(me.get("gold_earned")) or 0,
            "dmg": dmg, "magic": m, "phys": p, "true": t,
            "dmg_taken": _n(me.get("damage_taken")) or 0,
            "dmg_mit": _n(me.get("damage_self_mitigated")) or 0,
            "heal": _n(me.get("total_heal")) or 0,
            "vision": _n(me.get("vision_score")) or 0,
            "cs": cs,
            "level": _n(me.get("champ_level")) or 0,
            "duration": _n(r.get("game_duration")) or 0,
            "augments": me.get("augments") or [], "items": me.get("items") or [],
            "double": _n(me.get("double_kills")) or 0, "triple": _n(me.get("triple_kills")) or 0,
            "quadra": _n(me.get("quadra_kills")) or 0, "penta": _n(me.get("penta_kills")) or 0,
            "first_blood": bool(me.get("first_blood_kill")),
        })

    n = len(matches)
    wins = sum(1 for x in matches if x["win"])
    losses = n - wins
    win_rate = wins / n if n else 0.0
    tot_k = sum(x["kills"] for x in matches)
    tot_d = sum(x["deaths"] for x in matches)
    tot_a = sum(x["assists"] for x in matches)
    kda = (tot_k + tot_a) / tot_d if tot_d else None
    sum_magic = _sum(x["magic"] for x in matches)
    sum_phys = _sum(x["phys"] for x in matches)
    sum_true = _sum(x["true"] for x in matches)
    tot_dmg = sum_magic + sum_phys + sum_true
    dmg_break = {
        "magic": round(sum_magic / tot_dmg, 4) if tot_dmg else 0.0,
        "physical": round(sum_phys / tot_dmg, 4) if tot_dmg else 0.0,
        "true": round(sum_true / tot_dmg, 4) if tot_dmg else 0.0,
    }

    cg = defaultdict(list)
    for x in matches:
        cg[x["me"].get("champion_id")].append(x)
    by_champion = []
    for cid, xs in cg.items():
        cw = sum(1 for y in xs if y["win"])
        ck = sum(y["kills"] for y in xs)
        cd = sum(y["deaths"] for y in xs)
        ca = sum(y["assists"] for y in xs)
        by_champion.append({
            "champion_id": cid,
            "champion_name": xs[0]["me"].get("champion_name"),
            "games": len(xs), "wins": cw,
            "win_rate": cw / len(xs),
            "kda": (ck + ca) / cd if cd else None,
            "avg_damage": _avg([y["dmg"] for y in xs]),
            "avg_gold": _avg([y["gold"] for y in xs]),
            "avg_vision": _avg([y["vision"] for y in xs]),
            "avg_cs": _avg([y["cs"] for y in xs]),
            "top_augments": _top_ids([a for y in xs for a in y["augments"]]),
        })
    by_champion.sort(key=lambda z: -z["games"])

    recent_raw = sorted(matches, key=lambda x: x["row"].get("game_creation") or 0, reverse=True)[:15]
    recent = []
    for x in recent_raw:
        r = x["row"]
        me = x["me"]
        recent.append({
            "match_id": r.get("match_id"),
            "game_creation": r.get("game_creation"),
            "game_mode": r.get("game_mode"), "queue_id": r.get("queue_id"),
            "game_version": r.get("game_version"), "duration": x["duration"],
            "win": x["win"],
            "source": r.get("source"),
            "self": {
                "champion_id": me.get("champion_id"), "champion_name": me.get("champion_name"),
                "kills": x["kills"], "deaths": x["deaths"], "assists": x["assists"],
                "kda": round((x["kills"] + x["assists"]) / x["deaths"], 2) if x["deaths"] else None,
                "gold": x["gold"], "dmg_champ": x["dmg"],
                "magic": x["magic"], "phys": x["phys"], "true": x["true"],
                "dmg_taken": x["dmg_taken"], "dmg_mitigated": x["dmg_mit"], "heal": x["heal"],
                "vision": x["vision"], "cs": x["cs"],
                "items": me.get("items") or [], "augments": me.get("augments") or [],
                "primary_style": me.get("primary_style"), "secondary_style": me.get("secondary_style"),
                "perks": me.get("perks") or [],
                "multikills": {"double": x["double"], "triple": x["triple"],
                               "quadra": x["quadra"], "penta": x["penta"]},
                "first_blood": x["first_blood"],
            },
            "teams": [{"team_id": t.get("team_id"), "win": t.get("win"),
                       "tower_kills": t.get("tower_kills"), "dragon_kills": t.get("dragon_kills"),
                       "baron_kills": t.get("baron_kills"), "inhibitor_kills": t.get("inhibitor_kills"),
                       "nexus_kills": t.get("nexus_kills")} for t in (x["teams"] or [])],
            "participants": [
                {"summoner_name": p.get("summoner_name"), "champion_name": p.get("champion_name"),
                 "team_id": p.get("team_id"), "win": p.get("win"),
                 "kills": p.get("kills"), "deaths": p.get("deaths"), "assists": p.get("assists"),
                 "dmg_champ": p.get("damage_to_champions"), "gold": p.get("gold_earned")}
                for p in (x["parts"] or [])
            ],
        })

    sources = sorted({r.get("source") for r in rows if r.get("source")})
    confs = sorted({r.get("confidence") for r in rows if r.get("confidence")})
    asof = max((r.get("collected_at") or "") for r in rows)
    return {
        "kind": "real_personal",
        "prov": {"kind": "real_personal",
                 "source": "/".join(sources) or "self",
                 "confidence": "/".join(confs) or "secondary",
                 "asof": asof,
                 "note": "本人自采（LCU/WeGame），仅次级佐证；隐藏战绩取不到"},
        "summary": {
            "games": n, "wins": wins, "losses": losses, "win_rate": win_rate,
            "avg_kills": _avg([x["kills"] for x in matches]),
            "avg_deaths": _avg([x["deaths"] for x in matches]),
            "avg_assists": _avg([x["assists"] for x in matches]),
            "kda": kda,
            "avg_gold": _avg([x["gold"] for x in matches]),
            "avg_damage": _avg([x["dmg"] for x in matches]),
            "avg_damage_taken": _avg([x["dmg_taken"] for x in matches]),
            "avg_damage_mitigated": _avg([x["dmg_mit"] for x in matches]),
            "avg_heal": _avg([x["heal"] for x in matches]),
            "avg_vision": _avg([x["vision"] for x in matches]),
            "avg_cs": _avg([x["cs"] for x in matches]),
            "avg_champ_level": _avg([x["level"] for x in matches]),
            "avg_duration": _avg([x["duration"] for x in matches]),
            "aram_games": sum(1 for x in matches if x["row"].get("queue_id") == 450),
            "total_double": _sum(x["double"] for x in matches),
            "total_triple": _sum(x["triple"] for x in matches),
            "total_quadra": _sum(x["quadra"] for x in matches),
            "total_penta": _sum(x["penta"] for x in matches),
            "first_blood_count": sum(1 for x in matches if x["first_blood"]),
        },
        "damage_breakdown": dmg_break,
        "by_champion": by_champion,
        "recent": recent,
    }


# ----------------------------------------------------------------------------- real（hexdata 聚合）
def _hexdata_prov(citation: dict, ver: str):
    return {"kind": "real_aggregate", "source": "Hexdata (aggregate)",
            "confidence": "aggregate_hexdata", "asof": citation.get("reportPatch", ver),
            "buildId": citation.get("buildId"), "reportPatch": citation.get("reportPatch"),
            "reportDate": citation.get("reportDate"),
            "attribution": citation.get("attribution_text", "")}


def load_real_rankings(root: Path, ver: str, hero_meta: dict, aug_meta: dict):
    """hexdata top_heroes / top_augments → Wilson 排名（真实聚合）。"""
    agg = root / "data" / "agg"
    latest = agg / "LATEST"
    if not latest.exists():
        return {}, {"kind": "unavailable", "reason": "data/agg/LATEST 缺失"}
    bid = latest.read_text(encoding="utf-8").strip()
    adir = agg / bid
    citation = {}
    if (adir / "citation.json").exists():
        citation = json.loads((adir / "citation.json").read_text(encoding="utf-8"))
    prov = _hexdata_prov(citation, ver)
    prov["_collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    out = {}
    hp = adir / "top_heroes.csv"
    if hp.exists():
        src = [{"key": int(r["id"]), "name": r.get("name"),
                "games": int(float(r["games"])), "winRate": float(r["winRate"]),
                "pickRate": _num(r.get("pickRate"), 0.0),
                "wins": int(round(float(r["winRate"]) * float(r["games"]))),
                "tier_hint": r.get("tier")} for r in read_csv(hp)]
        ranked = wilson.rank_entities(src, RANK_METHOD)
        for r in ranked:
            info = hero_meta.get(r["key"], {})
            r["aliases"] = info.get("aliases", [])
            r["roles"] = info.get("roles", [])
        out["hero_ranking"] = {"prov": dict(prov), "rows": ranked}

    ap = adir / "top_augments.csv"
    if ap.exists():
        src = [{"key": int(r["id"]), "name": r.get("name"),
                "games": int(float(r["games"])), "winRate": float(r["winRate"]),
                "pickRate": _num(r.get("pickRate"), 0.0),
                "wins": int(round(float(r["winRate"]) * float(r["games"]))),
                "hexScore": _num(r.get("globalHexScore")),
                "coverageHeroCount": int(float(r.get("coverageHeroCount") or 0))}
               for r in read_csv(ap)]
        ranked = wilson.rank_entities(src, RANK_METHOD)
        for r in ranked:
            r["rarity"] = (aug_meta.get(r["key"]) or {}).get("rarity")
        out["augment_ranking"] = {"prov": dict(prov), "rows": ranked}
    return out, {}


def load_economy_leaders(root: Path):
    """hexdata ai-summary 的 economyRanking.leaders（若原始文件在本地存在）。"""
    agg = root / "data" / "agg"
    latest = agg / "LATEST"
    if not latest.exists():
        return []
    raw = agg / latest.read_text(encoding="utf-8").strip() / "raw" / "ai-summary.json"
    if not raw.exists():
        return []
    try:
        d = json.loads(raw.read_text(encoding="utf-8"))
        return d.get("economyRanking", {}).get("leaders", [])
    except (json.JSONDecodeError, OSError):
        return []


# ----------------------------------------------------------------------------- RESG（完整聚合，完整池 vs hexdata top12）
def load_resg_prov(root: Path) -> dict:
    """RESG citation + prov（来源/可信度/时效标签，A07 分级）。"""
    resg_root = root / "data" / "agg_resg"
    latest = resg_root / "LATEST"
    if not latest.exists():
        return {"kind": "unavailable"}
    ver = latest.read_text(encoding="utf-8").strip()
    cit_fp = resg_root / ver / "citation.json"
    citation = {}
    if cit_fp.exists():
        citation = json.loads(cit_fp.read_text(encoding="utf-8"))
    return {
        "kind": "real_aggregate_resg",
        "source": "RESG (aggregate, resg.top)",
        "confidence": "aggregate_resg",
        "asof": ver,
        "resg_version": ver,
        "attribution": citation.get("attribution_text", ""),
    }


def load_resg_rankings(root: Path, hero_meta: dict, aug_meta: dict, ver: str = None) -> dict:
    """RESG 完整英雄/海克斯 → Wilson 排名。

    与 load_real_rankings（hexdata top12）的区别：
      - 英雄 173 位完整池，海克斯 211 位完整池
      - 含 tier/wr/tm/wm/pr 完整字段
      - 额外带 RESG 独有字段（quality/topChampions）
    """
    resg_root = root / "data" / "agg_resg"
    latest = resg_root / "LATEST"
    prov = load_resg_prov(root)
    if not latest.exists():
        return {"resg_champions": {"prov": prov, "rows": []},
                "resg_augments": {"prov": prov, "rows": []}}

    resg_ver = latest.read_text(encoding="utf-8").strip()
    rdir = resg_root / resg_ver

    out = {}
    # champions
    ch_fp = rdir / "champions.json"
    if ch_fp.exists():
        items = json.loads(ch_fp.read_text(encoding="utf-8"))
        src = []
        for r in items:
            games = r.get("tm") or 0
            wins = r.get("wm") or 0
            wr = r.get("wr") or (wins / games if games else 0.0)
            src.append({
                "key": r["id"],
                "name": r.get("name"),
                "title": r.get("title", ""),
                "alias": r.get("alias", ""),
                "roles": r.get("roles", []),
                "icon_path": r.get("ip", ""),
                "games": games,
                "wins": wins,
                "winRate": wr,
                "pickRate": 0.0,  # RESG champions 无登场率字段
                "tier_hint": r.get("tier", ""),
            })
        ranked = wilson.rank_entities(src, RANK_METHOD)
        # 角色名称本地化
        role_zh_map = {"fighter": "战士", "tank": "坦克", "mage": "法师",
                       "assassin": "刺客", "marksman": "射手", "support": "辅助"}
        for r in ranked:
            r["roles"] = [role_zh_map.get(x, x) for x in (r.get("roles") or [])]
        out["resg_champions"] = {"prov": dict(prov), "rows": ranked}
    else:
        out["resg_champions"] = {"prov": dict(prov), "rows": []}

    # augments
    aug_fp = rdir / "augments.json"
    if aug_fp.exists():
        items = json.loads(aug_fp.read_text(encoding="utf-8"))
        src = []
        for r in items:
            games = r.get("tm") or 0
            wins = r.get("wm") or 0
            wr = r.get("wr") or (wins / games if games else 0.0)
            src.append({
                "key": r["id"],
                "name": r.get("name"),
                "description": r.get("description", ""),
                "games": games,
                "wins": wins,
                "winRate": wr,
                "pickRate": r.get("pr", 0.0),
                "tier_hint": r.get("tier", ""),
                "quality": r.get("quality", 0),
                "top_champions": r.get("topChampions", []),
            })
        ranked = wilson.rank_entities(src, RANK_METHOD)
        # 名称回填（用 meta augments 的稀有度）
        for r in ranked:
            r["rarity"] = (aug_meta.get(r["key"]) or {}).get("rarity")
        out["resg_augments"] = {"prov": dict(prov), "rows": ranked}
    else:
        out["resg_augments"] = {"prov": dict(prov), "rows": []}

    # items：RESG/hexdata 均无公开聚合胜率 → 展示 A12 元数据装备列表（870 件含模式归属）
    item_fp = root / "data" / "meta" / ver / "items_modes.csv"
    if item_fp.exists():
        item_rows = []
        for r in read_csv(item_fp):
            try:
                item_rows.append({
                    "id": int(r["id"]),
                    "name": r.get("name"),
                    "gold_total": _num(r.get("gold_total")),
                    "gold_base": _num(r.get("gold_base")),
                    "id_family": r.get("id_family", ""),
                    "modes": [x for x in (r.get("modes") or "").split("|") if x],
                    "maps": [x for x in (r.get("maps") or "").split("|") if x],
                    "aram_mode": (r.get("aram_mode") or "").lower() in ("true", "1"),
                    "tags": [x for x in (r.get("tags") or "").split("|") if x],
                })
            except (ValueError, KeyError):
                continue
        out["resg_items"] = {
            "prov": {
                "kind": "real_metadata",
                "source": "Data Dragon / CommunityDragon (A12)",
                "confidence": "authoritative",
                "asof": ver,
                "note": "装备聚合胜率数据源缺失（RESG/hexdata 均无公开端点），当前展示 A12 元数据装备列表（870 件）含模式归属标注；聚合胜率待数据源出现后接入。",
            },
            "rows": item_rows,
        }
    else:
        out["resg_items"] = {
            "prov": {"kind": "unavailable", "source": None, "confidence": None,
                     "reason": "items_modes.csv 未找到"},
            "rows": [],
        }

    return out


# ----------------------------------------------------------------------------- fixture（M3 派生）
FIXTURE_DIR = Path("data") / "derived" / "m3" / "synthetic"

FIXTURE_TABLES = {
    "fixture_hero_stats": "corpus_hero_stats.csv",
    "fixture_augment_stats": "corpus_augment_stats.csv",
    "fixture_item_stats": "corpus_item_stats.csv",
    "fixture_hero_augment_pairs": "corpus_hero_augment_pairs.csv",
    "fixture_hero_item_pairs": "corpus_hero_item_pairs.csv",
    "fixture_hero_augment_item_triples": "corpus_hero_augment_item_triples.csv",
    "fixture_player_mmr": "corpus_player_mmr.csv",
    "fixture_slices_hero_stats": "corpus_slices_hero_stats.csv",
}


def ensure_derived(root: Path, ver: str) -> bool:
    """M3 派生缺失时按需重建（合成夹具）。返回是否可用。"""
    if (root / FIXTURE_DIR / "stats_meta.json").exists():
        return True
    try:
        import model.run_m3 as run_m3  # noqa: PLC0415
    except ImportError:
        return False
    saved = sys.argv
    sys.argv = ["run_m3.py", "--corpus=synthetic", f"--ver={ver}"]
    try:
        run_m3.main()
    except SystemExit as e:  # pragma: no cover
        if e.code:
            return False
    finally:
        sys.argv = saved
    return (root / FIXTURE_DIR / "stats_meta.json").exists()


def load_fixture(root: Path, hero_meta: dict, aug_meta: dict, item_meta: dict) -> dict:
    """M3 合成夹具统计 → 各表 + 名称回填。缺表则 kind='unavailable'。"""
    d = root / FIXTURE_DIR
    out = {}
    if not (d / "stats_meta.json").exists():
        return {"__unavailable__": {"kind": "unavailable", "reason": "M3 派生缺失"}}
    prov = {"kind": "synthetic_fixture", "source": "synthetic fixture (engine validation only)",
            "confidence": "fixture", "corpus": "synthetic_fixture"}
    meta = json.loads((d / "stats_meta.json").read_text(encoding="utf-8"))

    for name, fname in FIXTURE_TABLES.items():
        fp = d / fname
        if not fp.exists():
            out[name] = {"prov": dict(prov), "rows": []}
            continue
        rows = []
        for r in read_csv(fp):
            row = {k: v for k, v in r.items() if not k.startswith("_")}
            # 数值归一：CSV 读进来全是字符串；id 类字段与统计字段统一转数值
            for k in ("key", "champion_id", "augment_id", "item_id", "games", "wins", "rank",
                      "matches"):
                if k in row and row[k] not in ("", None):
                    try:
                        row[k] = int(float(row[k]))
                    except (ValueError, TypeError):
                        pass
            for k in ("winRate", "pickRate", "wilson_lower", "wilson_center", "wilson_upper",
                      "lift_vs_hero", "lift_vs_global", "global_winRate", "expected_hero_wr",
                      "estimated_mmr"):
                if k in row and row[k] not in ("", None):
                    row[k] = float(row[k])
            for k in ("in_top20", "in_top40"):
                if k in row:
                    row[k] = str(row[k]).strip().lower() in ("true", "1", "yes")
            # 名称回填
            if "key" in row:
                row["name"] = (hero_meta.get(row["key"]) or aug_meta.get(row["key"])
                               or item_meta.get(row["key"]) or {}).get("name")
            if "champion_id" in row:
                row["champion_name"] = (hero_meta.get(row["champion_id"]) or {}).get("name")
            if "augment_id" in row:
                row["augment_name"] = (aug_meta.get(row["augment_id"]) or {}).get("name")
            if "item_id" in row:
                row["item_name"] = (item_meta.get(row["item_id"]) or {}).get("name")
            rows.append(row)
        out[name] = {"prov": dict(prov), "rows": rows}

    out["__meta__"] = {
        "kind": "synthetic_fixture",
        "planted": (meta.get("corpus") or {}).get("planted"),
        "n_records": (meta.get("corpus") or {}).get("n_records"),
        "mmr_recovery_corr": (meta.get("corpus") or {}).get("mmr_recovery_corr"),
        "anti_domination": meta.get("anti_domination"),
        "slice_summary": meta.get("slice_summary"),
        "strata": (meta.get("methodology") or {}).get("strata"),
    }
    return out


# ----------------------------------------------------------------------------- 组装
def build_bundle(root: Path = None, ver: str = None, ensure: bool = True) -> dict:
    root = root or project_root()
    ver = ver or pick_version(root)
    hero_meta = load_hero_meta(root, ver)
    aug_meta = load_augment_meta(root, ver)
    item_meta = load_item_meta(root, ver)
    hex_pool = load_hexdata_alias_pool(root)

    real, _ = load_real_rankings(root, ver, hero_meta, aug_meta)

    if ensure:
        ensure_derived(root, ver)
    fixture = load_fixture(root, hero_meta, aug_meta, item_meta)

    # hexdata 引用（必带四字段，A07）
    agg = root / "data" / "agg"
    citation = {}
    if (agg / "LATEST").exists():
        adir = agg / (agg / "LATEST").read_text(encoding="utf-8").strip()
        cf = adir / "citation.json"
        if cf.exists():
            citation = json.loads(cf.read_text(encoding="utf-8"))

    datasets = {}
    datasets.update(real)
    datasets.update({k: v for k, v in fixture.items() if not k.startswith("__")})

    # ---- RESG 完整聚合（完整英雄/海克斯池；装备维度 unavailable 占位）----
    resg = load_resg_rankings(root, hero_meta, aug_meta, ver)
    datasets.update({k: v for k, v in resg.items() if not k.startswith("__")})

    # ---- M5 版本化维度（离线直接消费，不依赖运行时扫目录）----
    versions = load_versions(root)
    metas_embed = build_metas_embed(root)
    version_changes = build_version_changes(root)
    agg_trend = build_aggregate_trend(root)
    risk_notes = load_risk_notes(root)
    personal = build_personal(root)

    warnings = [
        "hexdata 聚合为群体样本关联，非因果；引用须标注来源+buildId+patch+日期。",
        "fixture_* 为合成夹具（synthetic_fixture），仅用于引擎校验，绝非真实数据，不得用于对外结论。",
        "聚合趋势（trend）在 agg 快照不足 2 份时以 synthetic_fixture 合成演示序列展示，非真实趋势；"
        "真实趋势随定时抓取积累后自动替换。",
        "本人对局（personal）为 LCU/WeGame 自采，仅次级佐证，隐藏战绩取不到，不得与群体聚合混同为因果。",
    ]

    bundle = {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta_version": ver,
        "generated_by": "python/bridge/build_viz_bundle.py",
        "rank_method": RANK_METHOD,
        "methodology": {
            "wilson_z": wilson.Z_95,
            "sample_tiers": {"low": "<250", "medium": "250-999", "high": ">=1000"},
            "recommendation": {"recommend": ">=250", "strong": ">=1000"},
            "ranking": RANK_METHOD,
            "lift_definition": "lift_vs_hero = 组合胜率 − 该英雄边际胜率；lift_vs_global = 组合胜率 − 全局胜率",
        },
        "hexdata_citation": {
            "buildId": citation.get("buildId"),
            "reportPatch": citation.get("reportPatch"),
            "reportDate": citation.get("reportDate"),
            "attribution_text": citation.get("attribution_text"),
            "required_context": citation.get("required_context"),
        },
        # M5：版本注册表 + 各版本英雄字典（离线切换名/别名）
        "versions": versions,
        "metas": metas_embed,
        "version_changes": version_changes,
        "trend": agg_trend,
        "risk_notes": risk_notes,
        # 本人对局（LCU/WeGame 自采，次级佐证；无数据时为 unavailable 占位）
        "personal": personal,
        "alias_index": build_alias_index(hero_meta, hex_pool),
        "heroes": [{"key": k, "name": v["name"], "title": v["title"],
                    "roles": v["roles"], "aliases": v["aliases"]}
                   for k, v in sorted(hero_meta.items())],
        "economy_leaders": load_economy_leaders(root),
        "fixture_meta": fixture.get("__meta__", {"kind": "unavailable"}),
        "datasets": datasets,
        "warnings": warnings,
    }

    # 数据集清单（供前端/验收快速核对）
    bundle["dataset_index"] = {
        k: {"kind": v.get("prov", {}).get("kind", "?"), "rows": len(v.get("rows", []))}
        for k, v in datasets.items()}
    return bundle


def write_bundle(bundle: dict, root: Path = None) -> Path:
    root = root or project_root()
    out = root / BUNDLE_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    out.write_text(payload, encoding="utf-8")
    # 内联回退：同一份数据另存为 JS，供 <script src> 加载。
    # 目的：以 file:// 双击 index.html 打开时 fetch 会被 CORS 拦，走脚本标签则不受限 → 真正「打开即用」。
    js = out.with_suffix(".js")
    js.write_text("window.__SL_BUNDLE__=" + payload + ";\n", encoding="utf-8")
    return out


def main() -> None:
    root = project_root()
    args = sys.argv[1:]
    ver = next((a.split("=", 1)[1] for a in args if a.startswith("--ver=")), None)
    bundle = build_bundle(root, ver)
    out = write_bundle(bundle, root)
    size = out.stat().st_size
    print(f"[viz] 数据束 → {out.relative_to(root)}  ({size:,} 字节)")
    for k, v in sorted(bundle["dataset_index"].items()):
        flag = "真实" if v["kind"] == "real_aggregate" else (
            "夹具" if v["kind"] == "synthetic_fixture" else v["kind"])
        print(f"   {k:34s} {v['rows']:>5} 行  [{flag}]")
    print(f"[viz] 别名词典 {len(bundle['alias_index'])} 条｜英雄 {len(bundle['heroes'])} 位")
    empty = [k for k, v in bundle["dataset_index"].items() if v["rows"] == 0]
    if empty:
        print(f"[viz] ⚠️ 空数据集（需核实）：{empty}")
    print("[viz] ✅ 完成")


if __name__ == "__main__":
    main()
