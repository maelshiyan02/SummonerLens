# -*- coding: utf-8 -*-
"""校验技能原型标注表（skill_archetypes.csv）——M1 第 1 项验收脚本。

用法：
  python tools/verify_archetypes.py [version]           # 正常校验
  python tools/verify_archetypes.py [version] --self-test  # 故障注入自检（应 FAIL 退出）

断言（任一失败即退出码 1）：
  1. 行数 == 英雄池规模（默认 173）
  2. manual_tags 无空值
  3. 标签只取自词表 {mobility, cc, sustain, aoe, burst, range, poke}
  4. 近战英雄不得带 range
  5. 已知高 Poke 英雄必须含 poke
  6. 已知无控英雄（易大师）不得含 cc
  7. poke 集合规模在合理区间 [5, 25]

--self-test：把 6 号断言反转（要求易大师必须含 cc）→ 必然失败，用于证明断言「能变红」。
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOCAB = {"mobility", "cc", "sustain", "aoe", "burst", "range", "poke"}
MUST_POKE = ["Xerath", "Ziggs", "Velkoz", "Zoe", "Ezreal", "Hwei"]
NO_CC = ["MasterYi"]


def main() -> None:
    args = [a for a in sys.argv[1:]]
    self_test = "--self-test" in args
    args = [a for a in args if not a.startswith("--")]
    ver = args[0] if args else sorted(
        [p.name for p in (ROOT / "data/meta").iterdir() if p.is_dir()])[-1]
    csv_path = ROOT / "data/meta" / ver / "skill_archetypes.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    by_id = {r["championId"]: r for r in rows}
    fails = []

    def check(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    print(f"=== 校验 {csv_path.name}（版本 {ver}）{'[SELF-TEST]' if self_test else ''} ===")
    check("1. 行数==英雄池(173)", len(rows) == 173, f"实际 {len(rows)}")
    check("2. manual_tags 无空", all(r["manual_tags"].strip() for r in rows))

    bad_vocab = [(r["championId"], t) for r in rows
                 for t in r["manual_tags"].split("|") if t and t not in VOCAB]
    check("3. 标签⊆词表", not bad_vocab, str(bad_vocab[:5]))

    melee_range = [r["championId"] for r in rows
                   if r["ranged"] == "近战" and "range" in r["manual_tags"].split("|")]
    check("4. 近战无 range", not melee_range, str(melee_range))

    miss_poke = [c for c in MUST_POKE if "poke" not in by_id.get(c, {}).get("manual_tags", "").split("|")]
    check("5. 高Poke英雄含 poke", not miss_poke, str(miss_poke))

    if self_test:
        # 故障注入：故意要求易大师必须含 cc —— 因其确实无控，断言必然失败
        cc_ids = [c for c in NO_CC if "cc" in by_id.get(c, {}).get("manual_tags", "").split("|")]
        check("6. [SELF-TEST] 易大师必须含 cc（应 FAIL）", bool(cc_ids))
    else:
        has_cc = [c for c in NO_CC if "cc" in by_id.get(c, {}).get("manual_tags", "").split("|")]
        check("6. 无控英雄(易)不含 cc", not has_cc, str(has_cc))

    n_poke = sum(1 for r in rows if "poke" in r["manual_tags"].split("|"))
    check("7. poke 数在 [5,25]", 5 <= n_poke <= 25, f"实际 {n_poke}")

    print(f"=== {'全部通过 ✅' if not fails else '存在失败 ❌: ' + ', '.join(fails)} ===")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
