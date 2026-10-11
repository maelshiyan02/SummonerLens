# -*- coding: utf-8 -*-
"""SummonerLens Python 建模内核（M3）。

模块：
  - synergy : 英雄 × Augment × 装备 组合胜率 + Wilson 下界 + 协同增益（lift）
  - slices  : 按玩家分层（前20%/前40%/全量）切片聚合

纪律：只依赖标准库 + python/stats；纯函数，可单测。
"""
from . import synergy, slices  # noqa: F401

__all__ = ["synergy", "slices"]
