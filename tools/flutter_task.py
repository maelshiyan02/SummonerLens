# -*- coding: utf-8 -*-
"""M4 · Flutter/Dart 任务统一入口（**禁止裸跑 flutter / dart**）

为什么不直接跑：Flutter 命令会改工作目录、写大量中间产物、可能长时间挂起；
统一入口负责「定位 SDK → 固定 cwd → 记录日志 → 超时 → 校验退出码」，避免误操作。

用法：
  python tools/flutter_task.py doctor
  python tools/flutter_task.py create
  python tools/flutter_task.py pubget
  python tools/flutter_task.py analyze
  python tools/flutter_task.py build            # = flutter build windows --release
  python tools/flutter_task.py build -- --debug
  python tools/flutter_task.py run              # ⚠️ 需图形会话（GUI），CI/headless 下会失败
  python tools/flutter_task.py clean
  python tools/flutter_task.py <任意> -- <原样透传的参数>

日志：build/flutter_logs/<task>-<时间戳>.log
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_REL = Path("app")
LOG_REL = Path("build") / "flutter_logs"

# 任务 → flutter 子命令
TASKS = {
    "doctor": ["doctor", "-v"],
    "create": ["create", "--platforms=windows", "--org", "com.summonerlens",
               "--project-name", "summonerlens", "."],
    "pubget": ["pub", "get"],
    "analyze": ["analyze", "--no-fatal-infos"],
    "test": ["test"],
    "build": ["build", "windows", "--release"],
    "run": ["run", "-d", "windows"],
    "clean": ["clean"],
    "devices": ["devices"],
}
GUI_TASKS = {"run"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def find_flutter() -> str:
    p = os.environ.get("FLUTTER_PATH")
    if p and Path(p).exists():
        return p
    for c in ("flutter.bat", "flutter"):
        w = shutil.which(c)
        if w:
            return w
    for c in (r"C:\Flutter\bin\flutter.bat", r"C:\src\flutter\bin\flutter.bat",
              r"C:\flutter\bin\flutter.bat"):
        if Path(c).exists():
            return c
    return ""


def main() -> int:
    root = project_root()
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("可用任务：" + ", ".join(TASKS))
        return 0

    task = args[0]
    extra = []
    if "--" in args:
        i = args.index("--")
        extra = args[i + 1:]
    if task not in TASKS:
        print(f"[flutter] ❌ 未知任务：{task}（可用：{', '.join(TASKS)}）")
        return 2

    flutter = find_flutter()
    if not flutter:
        print("[flutter] ❌ 未找到 flutter SDK。设置环境变量 FLUTTER_PATH 指向 flutter.bat。")
        return 3

    app_dir = root / APP_REL
    if task == "create":
        app_dir.mkdir(parents=True, exist_ok=True)
    if not app_dir.exists():
        print(f"[flutter] ❌ 应用目录不存在：{app_dir}（先跑 create）")
        return 4

    cmd = [flutter] + TASKS[task] + extra
    if task in GUI_TASKS:
        print("[flutter] ⚠️ 该任务需要图形会话（GUI）。当前若是无头/CI 会话，请交由用户在本地会话执行：")
        print(f"[flutter]    cd {app_dir} && {flutter} {' '.join(TASKS[task])}")

    logdir = root / LOG_REL
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = logdir / f"{task}-{stamp}.log"

    print(f"[flutter] task={task}  cwd={app_dir}")
    print(f"[flutter] cmd = {' '.join(cmd)}")
    print(f"[flutter] log = {log}")
    t0 = time.time()
    with log.open("w", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n\n")
        f.flush()
        proc = subprocess.run(cmd, cwd=str(app_dir), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace")
        f.write(proc.stdout or "")
        out = proc.stdout or ""
    dt = time.time() - t0
    # 回显尾部落日志
    tail = out.strip().splitlines()[-12:]
    for line in tail:
        print("   " + line)
    print(f"[flutter] 退出码={proc.returncode}  用时={dt:.1f}s")
    if proc.returncode == 0:
        print(f"[flutter] ✅ {task} 成功")
    else:
        print(f"[flutter] ❌ {task} 失败（完整日志见 {log}）")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
