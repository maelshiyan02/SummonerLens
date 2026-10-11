# -*- coding: utf-8 -*-
"""M2 · WeGame 本人对局采集（合规 · 仅本人）。

🔴 合规红线（见 A02 / A07）：
  - **仅采集本人**（或已获授权的账号）对局；脚本内置「仅本人」强校验，非本人 id 一律拒绝。
  - **不碰强制破解隐藏战绩**（注入/爬取他人隐私数据违反 ToS）。
  - 局内**伤害/承伤统计口径有偏** ⇒ 输出一律标注 confidence = "secondary"（次级佐证）。

凭证（**不入库**，.gitignore 排除 data/personal/ 下所有非 *.jsonl 文件）：
  1) 环境变量：SUM_LENS_WEGAME_TOKEN / SUM_LENS_WEGAME_COOKIE
  2) 本地文件：data/personal/wegame_credential.json
     {
       "self_id": "本人QQ号或召唤师id",     # 用于「仅本人」校验（必填）
       "area": "大区id",                    # 如 12
       "token": "...",                      # 登录 token
       "cookie": "...",                     # 或 cookie 串
       "endpoints": {                       # 端点模板（需实测确认，见下方 TODO）
         "battle_list":   "https://m.wegame.com.cn/api/.../GetBattleList",
         "battle_detail": "https://m.wegame.com.cn/api/.../GetBattleDetail",
         "query_by_nick": "https://m.wegame.com.cn/api/mobile/lua/proxy/.../query_by_nick"
       }
     }

⚠️ 端点说明：A02 记录的四类端点中，`GetBattleReport` 与 `query_by_nick` 有完整前缀，
   其余（GetBattleList / GetBattleDetail）在调研里是省略写法 ⇒ **须由使用者在本地抓包补全**
   后填入 credential.endpoints。本脚本不臆造端点。

用法：
  python python/etl/fetch_wegame.py --self-check          # 逻辑自检（含「仅本人」故障注入）
  python python/etl/fetch_wegame.py --parse <raw.json>    # 离线解析已抓取的原始响应 -> jsonl
  python python/etl/fetch_wegame.py                        # 真实抓取（需凭证，本地运行）
  python python/etl/fetch_wegame.py --dry-run              # 只打印将要请求的 URL，不发请求

输出：data/personal/matches.jsonl（每行一条对局，UTF-8，NDJSON）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SummonerLens/0.1")
ENV_TOKEN = "SUM_LENS_WEGAME_TOKEN"
ENV_COOKIE = "SUM_LENS_WEGAME_COOKIE"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cred_path(root: Path) -> Path:
    return root / "data" / "personal" / "wegame_credential.json"


def _fetch_bytes(url: str, headers: dict, timeout: int = 30) -> bytes:
    """curl 优先（本机走系统/代理 CA），回退 urllib。"""
    cmd = ["curl", "-sSL", "--max-time", str(timeout), "-H", f"User-Agent: {UA}"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
        if out.returncode == 0 and out.stdout:
            return out.stdout
    except Exception:  # noqa: BLE001
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------- 凭证与合规校验 ----------

def load_credentials(root: Path):
    """读取凭证：环境变量优先，其次本地文件。无则返回 None。"""
    cp = cred_path(root)
    cred = {}
    if cp.exists():
        cred = json.loads(cp.read_text(encoding="utf-8"))
    if os.environ.get(ENV_TOKEN):
        cred["token"] = os.environ[ENV_TOKEN]
    if os.environ.get(ENV_COOKIE):
        cred["cookie"] = os.environ[ENV_COOKIE]
    if not cred.get("token") and not cred.get("cookie"):
        return None
    return cred


def assert_self(cred: dict, target_id) -> None:
    """🔴 「仅本人」强校验：目标 id 必须等于 self_id。

    这是本脚本最重要的合规闸门；任何情况下都不得绕过。
    """
    self_id = cred.get("self_id")
    if not self_id:
        raise PermissionError("凭证缺少 self_id，无法执行「仅本人」校验 —— 拒绝采集。")
    if str(target_id) != str(self_id):
        raise PermissionError(
            f"🔴 合规拦截：目标 id={target_id} 与本人 id={self_id} 不一致，"
            f"本项目仅采集本人数据，已拒绝。")
    return


def self_check(root: Path) -> int:
    """逻辑自检：验证「仅本人」闸门真的会拦（故障注入），并校验字段映射。"""
    ok = True

    # 1) 本人 id 放行
    try:
        assert_self({"self_id": "10001", "token": "x"}, "10001")
        print("[wegame] ✅ 本人 id 放行")
    except PermissionError as e:
        print(f"[wegame] ❌ 本人 id 被误拦：{e}")
        ok = False

    # 2) 非本人 id 必须被拦（故障注入 —— 应触发 PermissionError）
    try:
        assert_self({"self_id": "10001", "token": "x"}, "99999")
        print("[wegame] ❌ 非本人 id 未被拦截（闸门失效！）")
        ok = False
    except PermissionError:
        print("[wegame] ✅ 非本人 id 已被拦截（闸门有效）")

    # 3) 缺 self_id 必须被拦
    try:
        assert_self({"token": "x"}, "10001")
        print("[wegame] ❌ 缺 self_id 未拦截")
        ok = False
    except PermissionError:
        print("[wegame] ✅ 缺 self_id 已拦截")

    # 4) 字段映射自检（用一条合成原始记录验证 parse 不抛错且标注次级佐证）
    fake = {"gameId": "T1", "queueId": 2400, "gameMode": "KIWI",
            "gameCreation": 1750000000000, "gameDuration": 1300,
            "participants": [{"puuid": "self-10001", "championId": 157,
                              "kills": 9, "deaths": 4, "assists": 11, "win": True,
                              "totalDamageDealtToChampions": 25000,
                              "totalDamageTaken": 30000}],
            "gameVersion": "16.20.1"}
    rec = parse_battle(fake, {"self_id": "10001", "puuid": "self-10001"})
    if not rec or rec.get("confidence") != "secondary" or rec.get("is_self") is not True:
        print(f"[wegame] ❌ parse_battle 输出异常：{rec}")
        ok = False
    else:
        print(f"[wegame] ✅ parse_battle 正常（confidence={rec['confidence']}, is_self={rec['is_self']}）")

    if ok:
        print("[wegame] ✅ 自检通过")
        return 0
    print("[wegame] ❌ 自检失败")
    return 1


# ---------- 解析（宽松映射，原始数据不丢） ----------

def parse_battle(raw: dict, cred: dict) -> dict:
    """把 WeGame 原始对局响应映射为统一 match 记录。

    宽松策略：字段名尝试多种写法；无法识别的原始 JSON 存入 raw_excerpt，
    避免因接口字段变动而静默丢数据。
    """
    def g(*keys, default=None):
        for k in keys:
            if isinstance(raw, dict) and k in raw and raw[k] is not None:
                return raw[k]
        return default

    parts = g("participants", "playerList", "players") or []
    me = None
    self_puuid = cred.get("puuid")
    self_id = cred.get("self_id")
    for p in parts:
        pid = p.get("puuid") or p.get("accountId") or p.get("summonerId")
        if self_puuid and pid == self_puuid:
            me = p
            break
        # 回退：summonerId/qq 匹配 self_id
        for f in ("summonerId", "sSummonerId", "qq", "id"):
            if str(p.get(f)) == str(self_id):
                me = p
                break
        if me:
            break

    def pick(d, *keys, default=None):
        for k in keys:
            if isinstance(d, dict) and d.get(k) is not None:
                return d[k]
        return default

    return {
        "match_id": g("gameId", "battleId", "matchId"),
        "game_creation": g("gameCreation", "gameCreateTime", "createTime"),
        "game_duration": g("gameDuration", "duration"),
        "queue_id": g("queueId", "queueID"),
        "game_mode": g("gameMode", "mode"),
        "map_id": g("mapId", 12),
        "game_version": g("gameVersion", "version"),
        "champion_id": pick(me, "championId", "champId") if me else None,
        "champion_name": pick(me, "championName", "champName") if me else None,
        "kills": pick(me, "kills"),
        "deaths": pick(me, "deaths"),
        "assists": pick(me, "assists"),
        "win": pick(me, "win", "isWin"),
        "items": pick(me, "items", "itemIds", default=[]),
        "augments": pick(me, "augments", "augmentIds", default=[]),
        "damage_dealt": pick(me, "totalDamageDealtToChampions", "damageDealt", "totalDamageDealt"),
        "damage_taken": pick(me, "totalDamageTaken", "damageTaken"),
        "is_self": bool(me),
        # —— 来源与可信度标注（A07 硬要求）——
        "source": "wegame",
        "confidence": "secondary",       # 局内统计口径有偏，仅参考
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "raw_excerpt": json.dumps(raw, ensure_ascii=False)[:2000],
    }


# ---------- 抓取 ----------

def request_json(url: str, cred: dict, params: dict, dry=False):
    headers = {"Accept": "application/json"}
    if cred.get("cookie"):
        headers["Cookie"] = cred["cookie"]
    if cred.get("token"):
        headers["Authorization"] = f"Bearer {cred['token']}"
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    full = f"{url}?{qs}" if qs else url
    if dry:
        print(f"[wegame] (dry-run) GET {full}")
        return None
    return json.loads(_fetch_bytes(full, headers).decode("utf-8"))


def main() -> None:
    root = project_root()
    args = sys.argv[1:]

    if "--self-check" in args:
        sys.exit(self_check(root))

    if "--parse" in args:
        i = args.index("--parse")
        if i + 1 >= len(args):
            print("[wegame] 用法：--parse <raw.json>")
            sys.exit(2)
        raw = json.loads(Path(args[i + 1]).read_text(encoding="utf-8"))
        cred = load_credentials(root) or {"self_id": None}
        rec = parse_battle(raw, cred)
        out = root / "data" / "personal" / "matches.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[wegame] 已解析并追加 1 条 -> {out}")
        return

    cred = load_credentials(root)
    if cred is None:
        print("[wegame] ⚠️ 未找到本人凭证 —— 跳过采集（合规：本项目仅采集本人数据）。")
        print("         请提供以下任一：")
        print(f"           1) 环境变量 {ENV_TOKEN} / {ENV_COOKIE}")
        print(f"           2) 本地文件 {cred_path(root)}（见脚本 docstring 的字段说明）")
        print("         注：不带任何参数运行本脚本不会访问网络。")
        sys.exit(3)

    assert_self(cred, cred.get("self_id"))  # 自证：self_id 必须存在且等于自身
    eps = cred.get("endpoints") or {}
    missing = [k for k in ("battle_list", "battle_detail") if not eps.get(k)]
    if missing:
        print(f"[wegame] ⚠️ 端点未配置：{missing}")
        print("         A02 记录的部分 WeGame 端点为省略写法，须本地抓包补全后填入")
        print("         credential.endpoints，再运行。本脚本不臆造端点。")
        sys.exit(4)

    dry = "--dry-run" in args
    out = root / "data" / "personal" / "matches.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    lst = request_json(eps["battle_list"], cred, {
        "id": cred["self_id"], "area": cred.get("area"),
        "offset": 0, "limit": cred.get("limit", 20)}, dry=dry)
    if dry:
        print("[wegame] dry-run 结束（未发请求、未写文件）。")
        return

    games = (lst or {}).get("data", {}).get("games") or (lst or {}).get("games") or []
    n = 0
    for game in games:
        gid = game.get("gameId") or game.get("battleId")
        detail = request_json(eps["battle_detail"], cred, {
            "gameId": gid, "id": cred["self_id"], "area": cred.get("area")})
        rec = parse_battle(detail.get("data", detail) if isinstance(detail, dict) else {},
                           cred)
        assert_self(cred, cred.get("self_id"))
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
        time.sleep(0.4)
    print(f"[wegame] ✅ 采集完成，追加 {n} 条 -> {out}")


if __name__ == "__main__":
    main()
