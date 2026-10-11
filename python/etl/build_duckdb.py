# -*- coding: utf-8 -*-
"""M2 · 本地落库（DuckDB 汇聚三路数据）。

三路数据：
  1) 元数据（权威）  data/meta/<ver>/*.csv            <- Data Dragon / CommunityDragon
  2) 聚合统计（借）  data/agg/<buildId>/*.csv + .json  <- hexdata（须带四字段溯源）
  3) 本人对局（自采）data/personal/matches.jsonl        <- WeGame / LCU（次级佐证）

输出：data/summonerlens.duckdb（派生物，.gitignore 排除）

设计纪律：
  - 项目根**由脚本自身位置推导**；不写绝对路径。
  - 每张表都带「来源 + 可信度 + 时效」四列（A07 硬要求）：
      _source / _confidence / _asof / _collected_at
  - 缺哪一路数据不报错，但会打印明确提示（对局数据依赖本人凭证，允许缺席）。
  - 只依赖 duckdb（见托管 venv：.../envs/summonerlens）。
"""
import json
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:  # noqa: BLE001
    print("[duckdb] 缺少 duckdb 依赖。请用托管 venv 运行：")
    print("  C:/Users/Administrator/.workbuddy/binaries/python/envs/summonerlens/Scripts/python.exe "
          "python/etl/build_duckdb.py")
    raise SystemExit(2)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def q(p: Path) -> str:
    """DuckDB 里用的路径字面量（POSIX + 单引号转义）。"""
    return str(p).replace("\\", "/").replace("'", "''")


def pick_version(root: Path) -> str:
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        return sys.argv[1]
    metas = [p.name for p in (root / "data" / "meta").iterdir() if p.is_dir()]

    def key(v):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)
    return sorted(metas, key=key)[-1]


# —— 表定义： (表名, 源文件相对路径, 列注释来源) ——
def build_meta_tables(con, meta_dir: Path, ver: str) -> dict:
    """元数据表：来源 = Data Dragon/CommunityDragon，权威。"""
    spec = [
        ("meta_champions", "champions.csv"),
        ("meta_items", "items.csv"),
        ("meta_items_modes", "items_modes.csv"),
        ("meta_augments", "augments.csv"),
        ("meta_skill_archetypes", "skill_archetypes.csv"),
        ("meta_aliases", "aliases.csv"),
    ]
    counts = {}
    for tbl, fname in spec:
        fp = meta_dir / fname
        if not fp.exists():
            print(f"[duckdb]   跳过（缺文件）: {fname}")
            continue
        con.execute(f"""
            CREATE OR REPLACE TABLE {tbl} AS
            SELECT *, 'Riot Data Dragon / CommunityDragon' AS _source,
                   'authoritative' AS _confidence,
                   '{ver}' AS _asof,
                   strftime(now(), '%Y-%m-%dT%H:%M:%S') AS _collected_at
            FROM read_csv_auto('{q(fp)}', header=true)
        """)
        counts[tbl] = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    return counts


def build_agg_tables(con, agg_dir: Path, build_id: str, patch: str) -> dict:
    """聚合统计表：来源 = hexdata（自建样本），须带四字段溯源。"""
    spec = [
        ("agg_top_heroes", "top_heroes.csv"),
        ("agg_top_augments", "top_augments.csv"),
        ("agg_hero_aliases", "hero_aliases.csv"),
    ]
    counts = {}
    cite = json.dumps({
        "source": "Hexdata",
        "url": "https://hexdata.com.cn",
        "buildId": build_id, "reportPatch": patch,
    }, ensure_ascii=False).replace("'", "''")
    for tbl, fname in spec:
        fp = agg_dir / fname
        if not fp.exists():
            print(f"[duckdb]   跳过（缺文件）: {fname}")
            continue
        con.execute(f"""
            CREATE OR REPLACE TABLE {tbl} AS
            SELECT *, 'Hexdata (self-collected samples)' AS _source,
                   'aggregate_hexdata' AS _confidence,
                   '{patch}' AS _asof,
                   '{build_id}' AS _build_id,
                   '{cite}' AS _citation,
                   strftime(now(), '%Y-%m-%dT%H:%M:%S') AS _collected_at
            FROM read_csv_auto('{q(fp)}', header=true)
        """)
        counts[tbl] = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    return counts


def build_citation_table(con, agg_dir: Path) -> int:
    """引用溯源表（一行，供 UI/导出直接拼引用块）。"""
    fp = agg_dir / "citation.json"
    if not fp.exists():
        return 0
    doc = json.loads(fp.read_text(encoding="utf-8"))
    con.execute("CREATE OR REPLACE TABLE agg_citation("
                "source VARCHAR, source_url VARCHAR, build_id VARCHAR, "
                "report_patch VARCHAR, report_date VARCHAR, attribution_text VARCHAR, "
                "license VARCHAR, fetched_at VARCHAR, "
                "_source VARCHAR, _confidence VARCHAR, _asof VARCHAR, _collected_at VARCHAR)")
    con.execute("INSERT INTO agg_citation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        doc.get("source"), doc.get("source_url"), doc.get("buildId"),
        doc.get("reportPatch"), doc.get("reportDate"),
        doc.get("attribution_text"), doc.get("license"), doc.get("fetched_at"),
        "Hexdata (self-collected samples)", "aggregate_hexdata",
        doc.get("reportPatch"), doc.get("fetched_at"),
    ])
    return 1


def build_personal_table(con, personal_dir: Path) -> int:
    """本人对局表（若存在）。来源 = WeGame/LCU，次级佐证。"""
    fp = personal_dir / "matches.jsonl"
    if not fp.exists() or fp.stat().st_size < 5:
        print("[duckdb]   跳过（无本人对局数据；依赖本人 WeGame 凭证，本地运行时生成）")
        return 0
    con.execute(f"""
        CREATE OR REPLACE TABLE personal_matches AS
        SELECT *, 'WeGame / LCU (self, authorized)' AS _source,
               'secondary' AS _confidence,
               strftime(now(), '%Y-%m-%dT%H:%M:%S') AS _collected_at
        FROM read_json_auto('{q(fp)}', format='newline_delimited', union_by_name=true)
    """)
    return con.execute("SELECT count(*) FROM personal_matches").fetchone()[0]


def main() -> None:
    root = project_root()
    ver = pick_version(root)
    agg_root = root / "data" / "agg"
    latest = agg_root / "LATEST"
    if not latest.exists():
        print("[duckdb] ❌ 缺 data/agg/LATEST —— 请先运行 python/etl/fetch_hexdata.py")
        raise SystemExit(1)
    build_id = latest.read_text(encoding="utf-8").strip()
    agg_dir = agg_root / build_id
    citation = json.loads((agg_dir / "citation.json").read_text(encoding="utf-8"))
    patch = citation.get("reportPatch", "")

    db_path = root / "data" / "summonerlens.duckdb"
    if db_path.exists():
        db_path.unlink()  # 派生库，整库重建确保幂等
    con = duckdb.connect(str(db_path))

    print(f"[duckdb] 版本 = {ver} | hexdata build = {build_id} | patch = {patch}")
    print("[duckdb] 1) 元数据表（权威）")
    c1 = build_meta_tables(con, root / "data" / "meta" / ver, ver)
    for t, n in c1.items():
        print(f"   {t:26s} {n} 行")
    print("[duckdb] 2) 聚合统计表（hexdata）")
    c2 = build_agg_tables(con, agg_dir, build_id, patch)
    for t, n in c2.items():
        print(f"   {t:26s} {n} 行")
    n_cit = build_citation_table(con, agg_dir)
    print(f"   agg_citation               {n_cit} 行")
    print("[duckdb] 3) 本人对局表")
    n_per = build_personal_table(con, root / "data" / "personal")
    if n_per:
        print(f"   personal_matches           {n_per} 行")
    else:
        print("   personal_matches           0 行")

    # 视图：英雄池（元数据 × 聚合昵称）
    con.execute("""
        CREATE OR REPLACE VIEW v_heroes AS
        SELECT c.id, c.key, c.name, c.title, c.tags, c.attackrange,
               s.auto_tags, s.manual_tags, s.ranged,
               m.aliases AS local_aliases,
               a.alternateNames AS hexdata_aliases
        FROM meta_champions c
        LEFT JOIN meta_skill_archetypes s ON s.championId = c.id
        LEFT JOIN meta_aliases m ON m.championId = c.id
        LEFT JOIN agg_hero_aliases a ON a.id = c.key
    """)

    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()]
    views = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.views WHERE table_schema='main' "
        "AND table_name NOT LIKE 'duckdb_%' AND table_name NOT LIKE 'sqlite_%' "
        "AND table_name NOT LIKE 'pragma_%' ORDER BY table_name"
    ).fetchall()]
    meta = {
        "meta_version": ver,
        "hexdata_build": build_id,
        "hexdata_patch": patch,
        "tables": tables,
        "views": views,
        "row_counts": {**c1, **c2, "agg_citation": n_cit, "personal_matches": n_per},
        "source_tiers": {
            "authoritative": "Data Dragon / CommunityDragon（元数据）",
            "aggregate_hexdata": "Hexdata 自建样本（聚合统计，须带四字段溯源）",
            "secondary": "WeGame / LCU 本人对局（局内指标有偏，仅参考）",
        },
    }
    con.execute("CREATE OR REPLACE TABLE _pipeline_meta AS SELECT ?::VARCHAR AS doc", [
        json.dumps(meta, ensure_ascii=False)])
    con.close()

    # 供人类阅读的清单（随仓，便于跨版本 diff；db 本体 gitignore）
    (root / "data" / "pipeline_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[duckdb] 表 = {tables}")
    print(f"[duckdb] 视图 = {views}")
    print(f"[duckdb] ✅ 完成 -> {db_path}")
    print(f"[duckdb] 总计 {sum(meta['row_counts'].values())} 行")


if __name__ == "__main__":
    main()
