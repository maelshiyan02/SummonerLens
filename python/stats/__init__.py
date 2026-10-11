# -*- coding: utf-8 -*-
"""SummonerLens Python 统计内核（M3）。

模块：
  - wilson : Wilson 95% 置信区间/下界、样本分档、排序（raw / tier-then-wilson）
  - mmr    : ELO/MMR 期望得分、单步更新、序列估计、玩家分层（前20%/前40%/全量）

纪律：纯标准库（无第三方依赖），全部为纯函数，可单测（见 tools/test_m3_unit.py）。
口径来源见 .agent/memory/appendices/A04（统计与建模口径）。
"""

from . import mmr, wilson  # noqa: F401

__all__ = ["wilson", "mmr"]
