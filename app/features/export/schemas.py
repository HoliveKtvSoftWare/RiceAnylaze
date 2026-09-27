"""Export request payloads; stable names preserve the OpenAPI schema."""
from typing import List, Optional
from pydantic import BaseModel


class ExportRequest(BaseModel):
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0
    # 指定要汇总的分析类型；不传时按记录自身的类型推断（混合类型会报 400）
    taskType: Optional[str] = None
    # true 时不在这里等结果，立刻返回 taskId 让前端轮询（导出记录多时用）
    asyncMode: bool = False


class BatchExportRequest(BaseModel):
    # analysisIds 与 allCompleted 二选一：传 id 列表，或导出全部已完成记录
    analysisIds: Optional[List[str]] = None
    allCompleted: bool = False
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0
    taskType: Optional[str] = None
    asyncMode: bool = False


class BatchJsonExportRequest(BaseModel):
    analysisIds: Optional[List[str]] = None
