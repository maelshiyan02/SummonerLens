# -*- coding: utf-8 -*-
"""M? · LCU 本地客户端本人对局采集（合规 · 仅本人 · 最干净路径）。

为什么是 LCU：英雄联盟客户端运行时，在 127.0.0.1:<port> 暴露本地 HTTPS API，
用 lockfile 里的 password 做 basic auth、忽略自签证书即可拉**本人**全部对局。
不需要任何 WeGame/掌盟 token，也不需抓包，合规最稳、字段最全（A07 评「中高」）。

合规红线（同 A02 / A07）：
  - 本接口只暴露本机登录账号可见范围 ⇒ 天然「仅本人」，脚本不提供指定他人 id 的能力。
  - 局内伤害/承伤以 LCU 为准（较准），仍标注 confidence；隐藏战绩本接口也取不到。
  - 不向上传、不注入内存；纯本地读取。

依赖：仅标准库（urllib / ssl / json / pathlib）。

用法：
  python python/etl/fetch_lcu.py --self-check     # 逻辑自检（含故障注入）
  python python/etl/fetch_lcu.py --dry-run        # 仅打印将请求的端点，不发请求
  python python/etl/fetch_lcu.py                  # 正式采集（需英雄联盟客户端运行）
  python python/etl/fetch_lcu.py --queue 450 --limit 50

输出：data/personal/matches.jsonl（与 fetch_wegame.py 同 schema，source='lcu'）
"""
import base64
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path

UA = "SummonerLens/0.1 (+lcu etl; maelshiyan02)"

# 候选 lockfile 位置（按顺序探测；可用 --lockfile 或 env SUM_LENS_LCU_LOCKFILE 覆盖）
LOCKFILE_CANDIDATES = [
    "C:/Riot Games/League of Legends/lockfile",
    "D:/Riot Games/League of Legends/lockfile",
    "C:/Program Files/Riot Games/League of Legends/lockfile",
    "C:/WeGameApps/League of Legends/lockfile",
    "D:/WeGameApps/League of Legends/lockfile",
]

# 国服经 WeGame 启动：客户端装在 WeGame 目录下，lockfile 由 LeagueClient 子进程写出。
# 常见变体（含中文目录名、自定义盘符）——固定候选没命中时按这些前缀扫描。
WEGAME_INSTALL_PREFIXES = [
    "Riot Games/League of Legends",
    "WeGameApps/League of Legends",
    "WeGame/League of Legends",
    "Games/League of Legends",
    "Program Files/Riot Games/League of Legends",
    "Program Files (x86)/Riot Games/League of Legends",
    "Program Files/WeGameApps/League of Legends",
    "Program Files (x86)/WeGameApps/League of Legends",
    "Program Files/英雄联盟",
    "Program Files (x86)/英雄联盟",
    "游戏/League of Legends",
    "英雄联盟",
]
SCAN_DRIVES = ("C:", "D:", "E:", "F:")
# 扫描时跳过的顶层目录（系统/用户资料，既慢也不太可能装游戏）
SCAN_SKIP_TOP = {"windows", "users", "programdata", "$recycle.bin",
                 "system volume information", "perflogs", "recovery", "boot", "intel"}

# 海克斯大乱斗 = ARAM，queueId 450
DEFAULT_QUEUE = 450


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_lockfile(explicit: str | None = None) -> Path | None:
    if explicit and Path(explicit).exists():
        return Path(explicit)
    env = os.environ.get("SUM_LENS_LCU_LOCKFILE")
    if env and Path(env).exists():
        return Path(env)
    for c in LOCKFILE_CANDIDATES:
        if Path(c).exists():
            return Path(c)
    return None


def _looks_like_league_lockfile(path: str) -> bool:
    """lockfile 内容首段固定为进程名 'LeagueClient'（国服/外服一致）。"""
    try:
        head = open(path, encoding="utf-8", errors="ignore").read(80)
    except OSError:
        return False
    return "LeagueClient" in head or "riot" in head.lower()


def discover_lockfiles(roots=None, max_depth: int = 5, limit: int = 8) -> list:
    """深度受限扫描磁盘，寻找 LeagueClient 的 lockfile。

    为什么需要：国服 LOL 经 WeGame 发行，安装目录随用户/盘符/版本变化（自定义盘、
    WeGameApps、中文目录名等），固定候选经常打偏。客户端运行时 lockfile 必在盘上，
    扫到即可连，不依赖用户手填路径。
    roots 默认为各盘根；测试可传入临时目录。
    """
    if roots is None:
        roots = [d + "/" for d in SCAN_DRIVES]
    game_dirs = {"league of legends", "leagueclient", "riot games", "wegame",
                 "wegameapps", "英雄联盟", "league of legends (tm)"}
    hits: list = []
    for drive_root in roots:
        try:
            tops = [os.path.join(drive_root, d) for d in os.listdir(drive_root)]
        except OSError:
            continue
        for top in tops:
            if not os.path.isdir(top):
                continue
            if os.path.basename(top).lower() in SCAN_SKIP_TOP:
                continue
            for root, dirs, files in os.walk(top):
                depth = root[len(top):].count(os.sep)
                # 前两层放开（安装根层级不定），更深只沿游戏相关目录收敛，保证快
                dirs[:] = [d for d in dirs if depth < 2 or d.lower() in game_dirs]
                if depth >= max_depth:
                    dirs[:] = []
                    continue
                low = {f.lower() for f in files}
                if "lockfile" in low:
                    p = os.path.join(root, "lockfile")
                    if _looks_like_league_lockfile(p):
                        hits.append(p)
                        if len(hits) >= limit:
                            return hits
    return hits


def read_lockfile(path: Path):
    """lockfile 格式：<proc>:<pid>:<port>:<password>:<protocol>"""
    text = path.read_text(encoding="utf-8").strip()
    parts = text.split(":")
    if len(parts) < 5:
        raise ValueError(f"lockfile 格式异常（期望 5 段，实得 {len(parts)}）：{text[:40]}...")
    return int(parts[2]), parts[3]


def _get(port: int, password: str, path: str, dry: bool = False) -> dict | None:
    url = f"https://127.0.0.1:{port}{path}"
    if dry:
        print(f"[lcu] (dry-run) GET {url}")
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    token = base64.b64encode(f"riot:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "User-Agent": UA,
    })
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def get_current_summoner(port, password, dry: bool = False) -> dict:
    return _get(port, password, "/lol-summoner/v1/current-summoner", dry=dry) or {}


def get_matchlist(port, password, puuid, queue, beg, end, dry: bool = False) -> list:
    p = (f"/lol-match-history/v3/matchlist/account/{puuid}"
         f"?queue={queue}&begIndex={beg}&endIndex={end}")
    data = _get(port, password, p, dry=dry) or {}
    games = data.get("games") or data
    ids = games.get("gameIds") if isinstance(games, dict) else None
    return ids or []


def get_game_detail(port, password, game_id, dry: bool = False) -> dict:
    return _get(port, password, f"/lol-match-history/v1/games/{game_id}", dry=dry) or {}


def _participant_record(p: dict) -> dict:
    """把 LCU 单个 participant 映射为统一详细结构（participants 数组元素）。

    覆盖：基础（英雄/召唤师/队伍/召唤师技能/胜负）、战斗（K/D/A/等级/金）、
    伤害（对英雄拆分 魔/物/真 + 承伤 + 减伤 + 治疗）、视野（视野分/眼）、
    发育（补刀=小兵+野怪）、出装（6 格 + 饰品）、符文（主/副系 + 6 枚）、
    海克斯（ARAM 3 槽）、多杀（双/三/四/五）、关键贡献（一血/一塔）。
    """
    st = p.get("stats") or {}

    def _item(i):
        v = st.get(f"item{i}")
        return v if isinstance(v, int) and v > 0 else None
    items = [x for x in (_item(i) for i in range(7)) if x is not None]
    trinket = st.get("trinket")
    augments = [st.get(f"playerAugment{i}") for i in (1, 2, 3)]
    augments = [a for a in augments if isinstance(a, int) and a > 0]
    perks = [st.get(f"perk{i}") for i in range(6)]
    perks = [x for x in perks if isinstance(x, int)]

    return {
        "puuid": p.get("puuid") or p.get("playerPuuid") or p.get("summonerId"),
        "summoner_name": p.get("summonerName") or p.get("playerSummonerName"),
        "champion_id": p.get("championId"),
        "champion_name": p.get("championName"),
        "team_id": p.get("teamId"),
        "spell1_id": p.get("spell1Id"),
        "spell2_id": p.get("spell2Id"),
        "win": bool(st.get("win")),
        "kills": st.get("kills"), "deaths": st.get("deaths"), "assists": st.get("assists"),
        "champ_level": st.get("champLevel"),
        "gold_earned": st.get("goldEarned"),
        "damage_to_champions": st.get("totalDamageDealtToChampions"),
        "magic_dmg_champ": st.get("magicDamageDealtToChampions"),
        "physical_dmg_champ": st.get("physicalDamageDealtToChampions"),
        "true_dmg_champ": st.get("trueDamageDealtToChampions"),
        "damage_taken": st.get("totalDamageTaken"),
        "damage_self_mitigated": st.get("damageSelfMitigated"),
        "total_heal": st.get("totalHeal"),
        "vision_score": st.get("visionScore"),
        "wards_placed": st.get("wardsPlaced"),
        "wards_killed": st.get("wardsKilled"),
        "total_minions_killed": st.get("totalMinionsKilled"),
        "neutral_minions_killed": st.get("neutralMinionsKilled"),
        "items": items,
        "trinket": trinket if isinstance(trinket, int) and trinket > 0 else None,
        "primary_style": st.get("primaryPerkStyle"),
        "secondary_style": st.get("secondaryPerkStyle"),
        "perks": perks,
        "augments": augments,
        "double_kills": st.get("doubleKills"), "triple_kills": st.get("tripleKills"),
        "quadra_kills": st.get("quadraKills"), "penta_kills": st.get("pentaKills"),
        "first_blood_kill": bool(st.get("firstBloodKill")),
        "first_tower_kill": bool(st.get("firstTowerKill")),
    }


def parse_lcu_game(raw: dict, self_puuid: str) -> dict:
    """把 LCU 完整对局响应映射为统一「详细对局」记录（与 fetch_wegame.parse_battle 同 schema）。

    顶层：对局元数据 + self_puuid + 来源/可信度标注；
    participants：全部 10 名参与者（详细，见 _participant_record）；
    teams：双方队伍目标汇总。本人行由 self_puuid 在 participants 中定位（不重复存）。
    """
    game = raw.get("game") or raw
    parts = [_participant_record(p) for p in (game.get("participants") or [])]
    teams = []
    for t in (game.get("teams") or []):
        teams.append({
            "team_id": t.get("teamId"),
            "win": bool(t.get("win")),
            "tower_kills": t.get("towerKills"),
            "inhibitor_kills": t.get("inhibitorKills"),
            "dragon_kills": t.get("dragonKills"),
            "baron_kills": t.get("baronKills"),
            "rift_herald_kills": t.get("riftHeraldKills"),
            "nexus_kills": t.get("nexusKills"),
        })
    me = next((p for p in parts if self_puuid and str(p.get("puuid")) == str(self_puuid)), None)
    return {
        "match_id": game.get("gameId"),
        "game_creation": game.get("gameCreation"),
        "game_duration": game.get("gameDuration"),
        "queue_id": game.get("queueId"),
        "game_mode": game.get("gameMode"),
        "map_id": game.get("mapId", 12),
        "game_version": game.get("gameVersion"),
        "game_type": game.get("gameType"),
        "self_puuid": self_puuid,
        "is_self": bool(me),
        # —— 来源与可信度标注（A07 硬要求）——
        "source": "lcu",
        # LCU 本地最可靠（A07 评「中高」），高于 WeGame 的 secondary；隐藏战绩仍取不到。
        "confidence": "primary",
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "participants": parts,
        "teams": teams,
        "raw_excerpt": json.dumps(raw, ensure_ascii=False)[:500],
    }


def self_check() -> int:
    """逻辑自检：验证详细对局解析（10 参与者 / 2 队伍 / 本人字段齐全 / 伤害拆分 / 装备 / 符文 / 海克斯）
    + 故障注入（非本人不冒领；本人 stats 缺失时优雅降级不崩溃）。"""
    ok = True
    fake_self = "puuid-self-111"

    def _mk_part(puuid, cid, kn, dd, dt, items, augs, perks, win, team):
        return {"puuid": puuid, "championId": cid, "championName": kn, "teamId": team,
                "spell1Id": 4, "spell2Id": 7,
                "stats": {"win": win,
                          "kills": 9 if puuid == fake_self else 3,
                          "deaths": 4 if puuid == fake_self else 5,
                          "assists": 11 if puuid == fake_self else 6,
                          "champLevel": 18, "goldEarned": 14500,
                          "totalDamageDealtToChampions": dd,
                          "magicDamageDealtToChampions": int(dd * 0.48),
                          "physicalDamageDealtToChampions": int(dd * 0.4),
                          "trueDamageDealtToChampions": int(dd * 0.12),
                          "totalDamageTaken": dt, "damageSelfMitigated": 18000,
                          "totalHeal": 5000, "visionScore": 45, "wardsPlaced": 12,
                          "totalMinionsKilled": 60, "neutralMinionsKilled": 5,
                          "item0": (items[0] if len(items) > 0 else 0),
                          "item1": (items[1] if len(items) > 1 else 0),
                          "item2": (items[2] if len(items) > 2 else 0),
                          "playerAugment1": (augs[0] if len(augs) > 0 else 0),
                          "primaryPerkStyle": perks[0] if perks else 8000,
                          "secondaryPerkStyle": perks[1] if len(perks) > 1 else 8300,
                          "perk0": perks[0] if perks else 8112,
                          "perk1": perks[1] if len(perks) > 1 else 8124,
                          "doubleKills": 1, "firstBloodKill": True}}

    parts = [_mk_part(fake_self, 157, "疾风剑豪", 25000, 30000, [1, 2, 3], [10], [8000, 8300], True, 100)]
    for i in range(1, 10):
        parts.append(_mk_part(f"p{i}", 90 + i, f"英雄{i}", 18000, 25000, [4, 5], [11],
                              [8100, 8200], i < 3, 100 if i < 5 else 200))
    g_ok = {"game": {"gameId": 1, "queueId": 450, "gameMode": "ARAM", "gameVersion": "16.20.1",
                     "gameCreation": 1750000000, "gameDuration": 1300, "participants": parts,
                     "teams": [{"teamId": 100, "win": True, "towerKills": 3, "inhibitorKills": 0,
                                "dragonKills": 2, "baronKills": 0, "riftHeraldKills": 0, "nexusKills": 0},
                               {"teamId": 200, "win": False, "towerKills": 1, "inhibitorKills": 0,
                                "dragonKills": 1, "baronKills": 0, "riftHeraldKills": 0, "nexusKills": 0}]}}
    rec = parse_lcu_game(g_ok, fake_self)
    if not (rec["is_self"] and len(rec["participants"]) == 10 and len(rec["teams"]) == 2):
        print(f"[lcu] ❌ 详细解析异常：is_self={rec.get('is_self')}, "
              f"parts={len(rec['participants'])}, teams={len(rec['teams'])}")
        ok = False
    else:
        me = next(p for p in rec["participants"] if str(p["puuid"]) == fake_self)
        cond = (me["champion_id"] == 157 and me["kills"] == 9
                and me["damage_to_champions"] == 25000 and me["magic_dmg_champ"] == 12000
                and me["gold_earned"] == 14500 and me["items"] == [1, 2, 3]
                and me["augments"] == [10] and me["perks"][0] == 8000
                and rec["teams"][0]["tower_kills"] == 3
                and rec["source"] == "lcu" and rec["confidence"] == "primary")
        if not cond:
            print(f"[lcu] ❌ 本人详细字段解析异常：{me}")
            ok = False
        else:
            print("[lcu] ✅ 详细对局解析正常（10 参与者 / 2 队伍 / 本人字段齐全 / "
                  "伤害拆分 / 装备 / 符文 / 海克斯）")

    # 故障注入 1：本人不在参战列表 -> is_self 必须为 False（不冒领他人数据）
    g_other = {"game": {"gameId": 2,
                        "participants": [{"puuid": "someone-else", "championId": 99,
                                          "stats": {"kills": 1}}],
                        "teams": [{"teamId": 100, "win": True}]}}
    rec2 = parse_lcu_game(g_other, fake_self)
    if rec2["is_self"] is not False or len(rec2["participants"]) != 1:
        print(f"[lcu] ❌ 非本人对局被误标 is_self=True（冒领！）：{rec2}")
        ok = False
    else:
        print("[lcu] ✅ 非本人对局正确标 is_self=False（不冒领）")

    # 故障注入 2：本人存在但 stats 缺失 -> 不应崩溃，仍 is_self=True（字段为 None）
    g_broken = {"game": {"gameId": 3, "participants": [{"puuid": fake_self, "championId": 157}]}}
    try:
        rec3 = parse_lcu_game(g_broken, fake_self)
        if not rec3["is_self"] or rec3["participants"][0]["kills"] is not None:
            print(f"[lcu] ❌ stats 缺失时解析异常：{rec3['participants'][0]}")
            ok = False
        else:
            print("[lcu] ✅ stats 缺失时优雅降级（is_self=True，字段 None，不崩溃）")
    except Exception as e:  # noqa: BLE001
        print(f"[lcu] ❌ stats 缺失时崩溃：{type(e).__name__}: {e}")
        ok = False

    # 3) lockfile 自动发现：命中 LeagueClient 内容 + 无关 lockfile 不误判
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        lc = os.path.join(td, "WeGameApps", "League of Legends", "LeagueClient")
        os.makedirs(lc, exist_ok=True)
        with open(os.path.join(lc, "lockfile"), "w", encoding="utf-8") as f:
            f.write("LeagueClient:12345:55999:abc-secret:https\n")
        # 无关 lockfile（内容不是 LeagueClient）——必须被排除
        other = os.path.join(td, "SomeApp")
        os.makedirs(other, exist_ok=True)
        with open(os.path.join(other, "lockfile"), "w", encoding="utf-8") as f:
            f.write("OtherApp:1:2:3:4\n")
        found = discover_lockfiles(roots=[td])
        if len(found) != 1 or not found[0].endswith("LeagueClient" + os.sep + "lockfile"):
            print(f"[lcu] ❌ lockfile 自动发现异常（应恰好命中 1 个 LeagueClient）：{found}")
            ok = False
        else:
            print("[lcu] ✅ lockfile 自动发现正常（命中 LeagueClient、排除无关 lockfile）")

    if ok:
        print("[lcu] ✅ 自检通过")
        return 0
    print("[lcu] ❌ 自检失败")
    return 1


def main() -> None:
    root = project_root()
    args = sys.argv[1:]

    if "--self-check" in args:
        sys.exit(self_check())

    # 定位 lockfile：显式/env/固定候选 → 全盘深度扫描（国服 WeGame 版路径不定）
    lf = None
    if "--lockfile" in args:
        i = args.index("--lockfile")
        if i + 1 < len(args):
            lf = args[i + 1]
    lf = find_lockfile(lf)
    if lf is None and "--no-scan" not in args:
        print("[lcu] 固定候选未命中，正在扫描磁盘寻找 LeagueClient lockfile（约数秒）...")
        hits = discover_lockfiles()
        if hits:
            for h in hits:
                print(f"[lcu]   发现：{h}")
            lf = Path(hits[0])
    if lf is None or not Path(lf).exists():
        print("[lcu] ⚠️ 未找到英雄联盟客户端 lockfile（客户端未运行？）。")
        print("         说明：国服 LOL 经 WeGame 启动，客户端运行（含大厅）时 lockfile 必在盘上；")
        print("         请通过 WeGame 正常启动英雄联盟客户端后重试。")
        print("         或手动指定：--lockfile <路径>（加 --no-scan 可跳过磁盘扫描）")
        sys.exit(3)

    port, password = read_lockfile(lf)
    dry = "--dry-run" in args
    queue = DEFAULT_QUEUE
    if "--queue" in args:
        i = args.index("--queue")
        if i + 1 < len(args):
            queue = int(args[i + 1])
    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            limit = int(args[i + 1])

    if dry:
        print(f"[lcu] dry-run：port={port}，将查询 queue={queue} 本人对局")
        get_current_summoner(port, password, dry=True)
        get_matchlist(port, password, "<puuid>", queue, 0, limit - 1, dry=True)
        print("[lcu] dry-run 结束（未发真实请求、未写文件）")
        return

    me = get_current_summoner(port, password)
    puuid = me.get("puuid")
    name = me.get("displayName") or me.get("gameName") or "(未知)"
    if not puuid:
        print("[lcu] ❌ 无法读取当前召唤师 puuid（客户端未完全就绪？）")
        sys.exit(4)
    print(f"[lcu] 已登录账号：{name}（puuid={puuid[:8]}...）")

    out = root / "data" / "personal" / "matches.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    beg = 0
    step = 20
    while n < limit:
        ids = get_matchlist(port, password, puuid, queue, beg, beg + step - 1)
        if not ids:
            break
        for gid in ids:
            if n >= limit:
                break
            try:
                detail = get_game_detail(port, password, gid)
            except Exception as e:  # noqa: BLE001
                print(f"[lcu] ⚠️ 对局 {gid} 详情拉取失败，跳过：{type(e).__name__}")
                continue
            rec = parse_lcu_game(detail, puuid)
            if rec["is_self"]:
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            time.sleep(0.3)
        beg += step
    print(f"[lcu] ✅ 采集完成，追加 {n} 条本人对局 -> {out}")


if __name__ == "__main__":
    main()
