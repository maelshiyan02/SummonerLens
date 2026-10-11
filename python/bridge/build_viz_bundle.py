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
    aliases = read_csv(root / "data" / "meta" / ver / "aliases.csv")
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

    warnings = [
        "hexdata 聚合为群体样本关联，非因果；引用须标注来源+buildId+patch+日期。",
        "fixture_* 为合成夹具（synthetic_fixture），仅用于引擎校验，绝非真实数据，不得用于对外结论。",
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
