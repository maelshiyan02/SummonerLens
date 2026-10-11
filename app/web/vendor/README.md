# vendor · 第三方前端资源（离线内置）

## echarts.min.js

| 项 | 值 |
|---|---|
| 包 | `echarts`（Apache ECharts） |
| 版本 | **5.5.1** |
| 许可 | **Apache-2.0**（见 `echarts.LICENSE.txt` / `echarts.NOTICE.txt`） |
| 来源 | `https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js` |
| 大小 | 1,030,855 字节 |
| sha256 | `e84270bd0cd5bdf60fefc26d00c2a391cb2e81f4d26a7a9ee16185a54773a3cf` |

**为什么内置**：本项目要求「打开即用、可离线」（计划书 §九 / A03 §3）。因此**禁止**在页面里引用任何 CDN 外链，
`tools/verify_m4.py` 会断言 `index.html` / `js/*.js` 中不含 `http(s)://` 外部脚本引用。

**更新方式**（记录在此，勿手改）：

```bash
cd app/web/vendor
curl -sS -o echarts.min.js      https://cdn.jsdelivr.net/npm/echarts@<VER>/dist/echarts.min.js
curl -sS -o echarts.LICENSE.txt https://cdn.jsdelivr.net/npm/echarts@<VER>/LICENSE
curl -sS -o echarts.NOTICE.txt  https://cdn.jsdelivr.net/npm/echarts@<VER>/NOTICE
sha256sum echarts.min.js | tee echarts.sha256.txt
```

> ⚠️ 升级版本后必须同步更新本文件与 `echarts.package.json`，并重跑 `tools/verify_m4.py`。
