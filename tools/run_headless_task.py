# -*- coding: utf-8 -*-
"""M4 · 无头（headless）校验通道

一次跑完本阶段全部「不需要图形界面」的验证，并把结果按**期望方向**判定：
  - 正常模式必须全绿（退出码 0）
  - 故障注入模式必须变红（退出码 1）

为什么单独做一层：会话内没有渲染表面（GUI），像素/渲染只能在用户会话里做；
但「取数 → 统计 → 组 option → 断言」这条链完全可以无头跑，本脚本就是这条链的总闸。

用法：
  python tools/run_headless_task.py                 # 数据束 → node 单测 → 端到端验收（含本地服务）
  python tools/run_headless_task.py --with-render   # 追加 Chrome headless 出图
  python tools/run_headless_task.py --skip-build    # 不重建数据束，直接用现有产物
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
RESULTS = []


def find_node() -> str:
    n = shutil.which("node")
    if n:
        return n
    for c in (r"C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2-6\node.exe",):
        if Path(c).exists():
            return c
    return ""


def run(label: str, cmd, expect_zero=True):
    print("\n" + "─" * 60)
    print(f"▶ {label}")
    print("  $ " + " ".join(str(c) for c in cmd))
    t0 = time.time()
    r = subprocess.run([str(c) for c in cmd], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    dt = time.time() - t0
    tail = (r.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print("    " + line)
    got_zero = (r.returncode == 0)
    ok = (got_zero == expect_zero)
    RESULTS.append((label, ok, r.returncode, dt))
    print(f"  退出码={r.returncode}（期望{'0' if expect_zero else '非0'}）"
          f" 用时={dt:.1f}s  {'✅' if ok else '❌'}")
    if not ok and (r.stderr or "").strip():
        print("  stderr: " + (r.stderr or "").strip()[-300:])
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-render", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    node = find_node()
    print("=" * 64)
    print("SummonerLens · M4 无头校验通道")
    print(f"python = {PY}")
    print(f"node   = {node or '（未找到，将跳过 node 用例）'}")
    print("=" * 64)

    if not args.skip_build:
        run("重建可视化数据束（bridge）", [PY, "python/bridge/build_viz_bundle.py"])

    if node:
        run("node 单测：正常必须全绿",
            [node, "tools/test_m4_unit.js"], expect_zero=True)
        run("node 单测：故障注入必须变红",
            [node, "tools/test_m4_unit.js", "--self-test"], expect_zero=False)
    else:
        print("⚠️ 未找到 node，跳过前端逻辑单测")

    vcmd = [PY, "tools/verify_m4.py"]
    if args.with_render:
        vcmd.append("--with-render")
    run("端到端验收：正常必须全绿", vcmd, expect_zero=True)
    run("端到端验收：故障注入必须变红",
        [PY, "tools/verify_m4.py", "--self-test"], expect_zero=False)

    print("\n" + "=" * 64)
    print("汇总：")
    bad = 0
    for label, ok, rc, dt in RESULTS:
        print(f"  {'✅' if ok else '❌'} {label}  (退出码 {rc}, {dt:.1f}s)")
        if not ok:
            bad += 1
    print("=" * 64)
    if bad:
        print(f"❌ {bad} 项不符合期望 —— 无头校验未通过")
        return 1
    print("✅ 全部符合期望（正常全绿 / 注入全红）")
    print("\n提示：GUI 渲染（打开即用、图表实际出图）请在用户图形会话执行：")
    print("  1) python python/bridge/serve.py --open      # 浏览器查看仪表板")
    print("  2) python tools/flutter_task.py run          # 运行桌面壳")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
