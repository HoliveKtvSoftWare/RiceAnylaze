# -*- coding: utf-8 -*-
"""已注册的分析大类。

**新增一个族**：在本目录加 ``<族>.py``（导出 ``FAMILY``），然后在下面加一行。
共享核心（registry / 导出 / 统计 / 前端）都不需要改。
每个族的指标算法在同名的 ``app/domain/analysis/families/<族>.py``。
"""

from . import leaf, stem

ALL_FAMILIES = (stem.FAMILY, leaf.FAMILY)

__all__ = ["ALL_FAMILIES", "leaf", "stem"]
