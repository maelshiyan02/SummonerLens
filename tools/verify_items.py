# -*- coding: utf-8 -*-
"""M1 · 装备模式归属验收（ARAM Mayhem 装备核验）。

用法：
  python tools/verify_items.py 16.20.1            # 正常校验（全 PASS -> 退出码 0）
  python tools/verify_items.py 16.20.1 --self-test # 故障注入（必然 FAIL -> 退出码 1）

断言若失败必须以非零退出码结束（静默空结果 = FAIL），满足「断言可复跑、可反向验证」纪律。
"""
import csv
import json
import sys
from pathlib import Path

PASS, FAIL = "PASS", "FAIL"
_failures = []


def check(label: str, cond: bool) -> bool:
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _failures.append(label)
    return cond


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    root = project_root()
    ver = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    if ver is None:
        metas = [p.name for p in (root / "data" / "meta").iterdir() if p.is_dir()]
        ver = sorted(metas, key=lambda v: tuple(int(x) for x in v.split(".")))[-1]
    self_test = "--self-test" in sys.argv
    base = root / "data" / "meta" / ver
    print(f"== 校验版本 {ver}{'（故障注入自检）' if self_test else ''} ==")

    rows = list(csv.DictReader((base / "items_modes.csv").open(encoding="utf-8-sig")))
    summary = json.loads((base / "item_modes_summary.json").read_text(encoding="utf-8"))
    aram = json.loads((base / "aram_mayhem_items.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows}

    # 1. 行数与 DD 一致
    check("1. items_modes.csv 行数 == 870", len(rows) == 870)

    # 2. DD vs CDragon 装备集完全一致（无人在 item.json 之外）
    check("2. DD 与 CDragon 装备集一致（零差异）", summary["cross_check"]["identical"] is True)

    # 3. jade 清单全为 77 系
    check("3. jade-items.json 全为 77xxxx 系", summary["jade_all_77"] is True)

    # 4. 海克斯专属 5 件均在库且 maps 含 12
    excl = aram["exclusive"]
    check("4a. 海克斯专属(confirmed) == 5 件", len(excl) == 5)
    check("4b. 专属装备均在库且属 map 12",
          all(i in by_id and "12" in by_id[i]["maps"].split("|") for i in [x["id"] for x in excl]))

    # 5. 模式列非空的一致性：maps 为空则 modes 也应为空
    ok = all((r["maps"] == "") == (r["modes"] == "") for r in rows)
    check("5. maps 与 modes 列一致性", ok)

    # 6. id_family 覆盖：base + copy_* 合计 == 总数
    fam_total = sum(summary["id_family_count"].values())
    check("6. id_family 计数合计 == 装备总数", fam_total == len(rows))
    check("6b. 存在 jade_copy 家族（77xxxx）", summary["id_family_count"].get("jade_copy", 0) > 0)

    # 7. 占位名装备数量稳定（数据质量标记）
    broken = summary["name_broken"]
    check("7. 占位名装备 == 4 件", len(broken) == 4)

    # 8. ARAM(map12) 池规模合理
    check("8. ARAM(map12) 池 ∈ [200,300]", 200 <= summary["aram_pool_size"] <= 300)

    if self_test:
        # 故障注入：断言「嘉文一世之靴(1111) 可在召唤师峡谷买」——事实为 maps={12}，必然 FAIL
        cond = by_id.get("1111", {}).get("maps", "") == "11"
        check("9. [SELF-TEST] 1111 应存在于 map 11（应 FAIL）", cond)
        # 故障注入 2：断言 DD 装备数 == 0（应 FAIL）
        check("10. [SELF-TEST] 装备总数应为 0（应 FAIL）", len(rows) == 0)

    print(f"\n合计：{'全部通过 ✅' if not _failures else f'{len(_failures)} 项失败 ❌'}")
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
