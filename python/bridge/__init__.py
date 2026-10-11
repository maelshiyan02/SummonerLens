# -*- coding: utf-8 -*-
"""M4 · Flutter ↔ Python 桥（数据束构建 + 本地服务）。

- `build_viz_bundle`：把 M1~M3 产物聚合成单一 JSON（app/web/data/dashboard.json）。
- `serve`：把 app/web 以本地 HTTP 提供，供 Flutter webview 加载。
"""
from . import build_viz_bundle, serve  # noqa: F401
