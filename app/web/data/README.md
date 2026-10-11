# app/web/data · 可视化数据束（派生目录）

本目录存放**派生**的可视化数据束，**不入库**（见仓库根 `.gitignore`）。

| 文件 | 说明 |
|---|---|
| `dashboard.json` | 仪表板唯一数据源，由 `python/bridge/build_viz_bundle.py` 从 M1~M3 产物聚合而成 |

## 生成方式

```bash
python python/bridge/build_viz_bundle.py          # 手动生成
python python/bridge/serve.py --open              # 缺省时自动生成并起本地服务
python tools/run_headless_task.py                 # 无头校验通道（会先重建）
```

## 数据分区（**绝不混用**，见 A14 §5 / A15）

- `hero_ranking` / `augment_ranking`：**hexdata 真实聚合**（`data/agg/<buildId>/top_*.csv`，随仓提交），
  kind = `real_aggregate`，引用必带 buildId + reportPatch + reportDate。
- `fixture_*`：**M3 合成夹具**（`data/derived/m3/synthetic/*.csv`），kind = `synthetic_fixture`，
  **仅用于引擎数值校验，绝不作为对外结论**。仪表板对夹具页会显著标注警示条。

每一项数据集都带 `prov.kind / source / confidence`，`tools/verify_m4.py` 会断言两者的来源标注不得互换。
