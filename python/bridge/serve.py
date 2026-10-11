# -*- coding: utf-8 -*-
"""M4 · 本地可视化服务（bridge）

把 `app/web/` 以 **仅本机回环** 的 HTTP 提供给 Flutter webview / 浏览器加载。
零第三方依赖，纯标准库。

为什么需要它：webview 直接以 `file://` 打开页面时，`fetch()` 读本地 JSON 会被 CORS 拦；
用 `http://127.0.0.1:<port>/` 提供则无障碍，且与「本地优先、零后端」定位一致。

安全：**只绑定 127.0.0.1**（绝不 0.0.0.0）；不暴露仓库其它目录。

CLI:
  python python/bridge/serve.py [--port=8760] [--no-build] [--open]
    --port=0      由系统分配空闲端口（实际端口打印到 stdout，供 Flutter 解析）
    --no-build    启动时不检查/构建数据束
    --open        启动后用系统浏览器打开（仅本机调试用）
启动时会向 stdout 打印一行： `SUMMONERLENS_SERVE http://127.0.0.1:<port>/`
"""
import argparse
import json
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # python/
from bridge import build_viz_bundle  # noqa: E402

WEB_REL = Path("app") / "web"
MARKER = "SUMMONERLENS_SERVE"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def web_dir() -> Path:
    return project_root() / WEB_REL


class Handler(SimpleHTTPRequestHandler):
    """静态资源 + 少量 API。禁缓存（数据束会随重建变化）。"""

    def __init__(self, *a, directory=None, **kw):
        super().__init__(*a, directory=str(directory), **kw)

    def log_message(self, fmt, *args):  # 静音默认日志，避免污染 stdout 协议行
        if self.path.startswith("/api/"):
            sys.stderr.write("[serve] %s - %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        super().end_headers()

    def guess_type(self, path):
        ctype = super().guess_type(path)
        if ctype.startswith(("text/", "application/javascript", "application/json")):
            return ctype if "charset" in ctype else ctype + "; charset=utf-8"
        return ctype

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            bundle_fp = web_dir() / "data" / "dashboard.json"
            info = {"ok": True, "web_dir": str(web_dir())}
            if bundle_fp.exists():
                try:
                    b = json.loads(bundle_fp.read_text(encoding="utf-8"))
                    info["bundle"] = {"schema": b.get("schema"),
                                      "generated_at": b.get("generated_at"),
                                      "datasets": b.get("dataset_index")}
                except (json.JSONDecodeError, OSError) as e:
                    info["ok"] = False
                    info["error"] = f"数据束损坏：{e}"
            else:
                info["ok"] = False
                info["error"] = "数据束缺失（app/web/data/dashboard.json）"
            return self._json(info)
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] == "/api/rebuild":
            try:
                out = build_viz_bundle.write_bundle(build_viz_bundle.build_bundle())
                return self._json({"ok": True, "bytes": out.stat().st_size})
            except Exception as e:  # noqa: BLE001  桥层要兜住任何构建异常
                return self._json({"ok": False, "error": str(e)}, 500)
        return self._json({"ok": False, "error": "not found"}, 404)


def ensure_bundle() -> None:
    fp = web_dir() / "data" / "dashboard.json"
    if not fp.exists():
        print("[serve] 数据束缺失，构建中 ...", file=sys.stderr)
        build_viz_bundle.write_bundle(build_viz_bundle.build_bundle())


def main() -> None:
    ap = argparse.ArgumentParser(description="SummonerLens 本地可视化服务")
    ap.add_argument("--port", type=int, default=8760, help="0 = 系统分配空闲端口")
    ap.add_argument("--no-build", action="store_true", help="启动时不构建数据束")
    ap.add_argument("--open", action="store_true", help="启动后用系统浏览器打开")
    args = ap.parse_args()

    if not web_dir().exists():
        print(f"[serve] ❌ 找不到 {web_dir()}", file=sys.stderr)
        raise SystemExit(2)
    if not args.no_build:
        ensure_bundle()

    handler = partial(Handler, directory=web_dir())
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    host, port = httpd.socket.getsockname()
    url = f"http://127.0.0.1:{port}/"
    print(f"{MARKER} {url}", flush=True)
    print(f"[serve] 提供目录：{web_dir()}", file=sys.stderr)

    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] 已停止", file=sys.stderr)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    _t0 = time.time()
    main()
