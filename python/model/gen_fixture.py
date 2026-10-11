# -*- coding: utf-8 -*-
"""M3 · 确定性合成对局夹具生成器（⚠️ 仅用于引擎校验，非真实数据）。

⚠️ 本脚本生成的是**合成（synthetic）**对局，唯一用途是验证 M3 统计/建模引擎的数值正确性
   （Wilson 排序、协同 lift、MMR 反推、分层切片）。它**不是**真实玩家数据，**绝不**用于对外结论，
   **绝不**与真实数据混合。每条记录都带 `source="synthetic_fixture"` / `confidence="fixture"` /
   `is_synthetic=true` 标注。固定 seed ⇒ 同 seed 同输出（可复现）。

产物（派生，可由本脚本重建；.gitignore 排除）：
  data/sample/m3_corpus.synth.jsonl          对局记录（NDJSON）
  data/sample/m3_corpus.synth.manifest.json  植入真值清单（供 tools/verify_m3.py 断言）

id 口径（与真实对局一致，便于未来替换为真数据）：
  英雄数值 id  = data/meta/<ver>/champions.csv 的 key 列
  Augment 数值 id = augments.csv 的 platform_id 列
  装备数值 id  = items.csv 的 id 列

植入设计（关键：植入英雄**不进入背景池**，避免被随机背景样本稀释）：
  - anchor_hero : 1200 局、effect +0.045 → high 档、tier-then-wilson 榜首
  - solid_hero  : 350 局、effect +0.060  → medium 档
  - trap_hero   : 40 局、 effect +0.350  → low 档、raw 胜率榜第一（官方方法必须压下去）
  - combo_block : 6 组 (英雄, Augment, 装备) —— 每组 150 局中性底样本 + 100 局植入 effect，
                  effect ∈ {+0.20,-0.20,+0.15,-0.12,+0.08,-0.10}；
                  底样本把英雄边际胜率拉回 ~0.5，从而把"协同增益"与"英雄本身强度"分离。
"""
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stats import mmr  # noqa: E402

SEED = 20261011
N_PLAYERS = 80
MIN_MATCHES_PER_PLAYER = 15
MAX_MATCHES_PER_PLAYER = 30

ANCHOR_GAMES, ANCHOR_EFFECT = 1200, 0.045
SOLID_GAMES, SOLID_EFFECT = 350, 0.060
TRAP_GAMES, TRAP_EFFECT = 40, 0.350

COMBO_EFFECTS = [0.20, -0.20, 0.15, -0.12, 0.08, -0.10]
COMBO_GAMES = 100
COMBO_BASE_GAMES = 150   # 每组 combo 英雄的中性底样本（隔离"英雄本身强度"）


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


def load_pools(meta_dir: Path):
    champs = [int(r["key"]) for r in csv.DictReader(
        (meta_dir / "champions.csv").open(encoding="utf-8-sig"))]
    augments = [int(r["platform_id"]) for r in csv.DictReader(
        (meta_dir / "augments.csv").open(encoding="utf-8-sig"))
        if r.get("in_pool_kiwi") == "True"]
    items = [int(r["id"]) for r in csv.DictReader(
        (meta_dir / "items.csv").open(encoding="utf-8-sig"))]
    return champs, augments, items


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def gen(root: Path, ver: str):
    rng = random.Random(SEED)
    champs, augments, items = load_pools(root / "data" / "meta" / ver)

    shuf = champs[:]
    rng.shuffle(shuf)
    anchor_hero, solid_hero, trap_hero = shuf[0], shuf[1], shuf[2]
    combo_heroes = shuf[3:3 + len(COMBO_EFFECTS)]
    aug_shuf = augments[:]
    rng.shuffle(aug_shuf)
    combo_augs = aug_shuf[:len(COMBO_EFFECTS)]
    item_shuf = items[:]
    rng.shuffle(item_shuf)
    combo_items = item_shuf[:len(COMBO_EFFECTS)]

    combo_block = [
        {"hero": combo_heroes[i], "augment": combo_augs[i], "item": combo_items[i],
         "effect": COMBO_EFFECTS[i]}
        for i in range(len(COMBO_EFFECTS))
    ]

    planted = {anchor_hero, solid_hero, trap_hero} | set(combo_heroes)
    background_pool = [c for c in champs if c not in planted]

    player_skill = {f"P{i:03d}": clamp(rng.gauss(1500, 220), 700, 2300)
                    for i in range(N_PLAYERS)}
    pids = list(player_skill)
    records = []

    def push(hero, augs, its, effect):
        pid = rng.choice(pids)
        opp = clamp(rng.gauss(1500, 150), 700, 2300)
        p = clamp(mmr.expected_score(player_skill[pid], opp) + effect, 0.02, 0.98)
        win = rng.random() < p
        records.append({
            "match_id": f"SYNTH_{len(records):06d}",
            "queue_id": 2400, "game_mode": "KIWI", "map_id": 12,
            "game_version": ver,
            "player_id": pid,
            "champion_id": hero,
            "augments": augs,
            "items": its,
            "win": win,
            "opp_avg_rating": round(opp, 1),
            "source": "synthetic_fixture",
            "confidence": "fixture",
            "is_synthetic": True,
        })

    def random_augs(exclude=()):
        pool = [a for a in augments if a not in exclude]
        return rng.sample(pool, 2)

    def random_items(exclude=()):
        pool = [i for i in items if i not in exclude]
        return rng.sample(pool, 3)

    # 1) 植入英雄（anchor / solid / trap）
    for _ in range(ANCHOR_GAMES):
        push(anchor_hero, random_augs(), random_items(), ANCHOR_EFFECT)
    for _ in range(SOLID_GAMES):
        push(solid_hero, random_augs(), random_items(), SOLID_EFFECT)
    for _ in range(TRAP_GAMES):
        push(trap_hero, random_augs(), random_items(), TRAP_EFFECT)

    # 2) 植入组合块：每组先中性底样本，再植入 (英雄,Augment,装备) 组合
    for cb in combo_block:
        for _ in range(COMBO_BASE_GAMES):
            push(cb["hero"], random_augs(exclude=(cb["augment"],)),
                 random_items(exclude=(cb["item"],)), 0.0)
        for _ in range(COMBO_GAMES):
            extra_aug = random_augs(exclude=(cb["augment"],))[0]
            its = [cb["item"]] + random_items(exclude=(cb["item"],))[:2]
            push(cb["hero"], [cb["augment"], extra_aug], its, cb["effect"])

    # 3) 背景对局（每玩家 15~30 局，英雄取自背景池）
    for pid in pids:
        for _ in range(rng.randint(MIN_MATCHES_PER_PLAYER, MAX_MATCHES_PER_PLAYER)):
            opp = clamp(rng.gauss(1500, 150), 700, 2300)
            records.append({
                "match_id": f"SYNTH_{len(records):06d}",
                "queue_id": 2400, "game_mode": "KIWI", "map_id": 12,
                "game_version": ver,
                "player_id": pid,
                "champion_id": rng.choice(background_pool),
                "augments": random_augs(),
                "items": random_items(),
                "win": rng.random() < clamp(mmr.expected_score(player_skill[pid], opp), 0.02, 0.98),
                "opp_avg_rating": round(opp, 1),
                "source": "synthetic_fixture", "confidence": "fixture", "is_synthetic": True,
            })

    rng.shuffle(records)

    manifest = {
        "seed": SEED, "meta_version": ver,
        "note": "SYNTHETIC FIXTURE — 仅用于 M3 引擎数值校验，非真实数据，勿用于结论",
        "n_players": N_PLAYERS, "n_records": len(records),
        "anchor_hero": anchor_hero, "solid_hero": solid_hero, "trap_hero": trap_hero,
        "combo_block": combo_block,               # [0] 为强协同，[1] 为弱协同
        "strong_combo": combo_block[0],
        "weak_combo": combo_block[1],
        "expected": {
            "anchor_tier": "high", "solid_tier": "medium", "trap_tier": "low",
            "anchor_games": ANCHOR_GAMES, "solid_games": SOLID_GAMES, "trap_games": TRAP_GAMES,
            "combo_games": COMBO_GAMES,
        },
        "player_skills": {k: round(v, 1) for k, v in player_skill.items()},
    }
    return records, manifest


def main() -> None:
    root = project_root()
    ver = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else pick_version(root)
    records, manifest = gen(root, ver)
    out = root / "data" / "sample"
    out.mkdir(parents=True, exist_ok=True)
    jl = out / "m3_corpus.synth.jsonl"
    mf = out / "m3_corpus.synth.manifest.json"
    with jl.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fixture] version={ver} 记录 {len(records)} 条 -> {jl}")
    print(f"[fixture] 植入：anchor={manifest['anchor_hero']} solid={manifest['solid_hero']} "
          f"trap={manifest['trap_hero']}")
    print(f"[fixture] 组合块 {len(manifest['combo_block'])} 组；强协同 {manifest['strong_combo']}；"
          f"弱协同 {manifest['weak_combo']}")
    print(f"[fixture] 清单 -> {mf}")


if __name__ == "__main__":
    main()
