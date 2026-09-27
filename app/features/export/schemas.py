"""Export request payloads; stable names preserve the OpenAPI schema."""
from typing import List, Optional
from pydantic import BaseModel


class ExportRequest(BaseModel):
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0
    # 仅对 /summary 生效：指定要汇总的分析类型；单条/批量以记录自身类型为准
    taskType: Optional[str] = None


class BatchExportRequest(BaseModel):
    analysisIds: List[str]
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0
    taskType: Optional[str] = None


class BatchJsonExportRequest(BaseModel):
    analysisIds: Optional[List[str]] = None
