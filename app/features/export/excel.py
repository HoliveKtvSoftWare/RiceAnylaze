# -*- coding: utf-8 -*-
"""把一条分析记录（LabelMe JSON）换算成一行 Excel 数据。

**本类不认识任何具体分析大类**：列定义与指标算法都通过 registry 从记录所属的族取。
因此新增一个族（茎秆 / 剑叶之外的第三类）不需要改这个文件。
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd
from fastapi import HTTPException
from io import BytesIO
from sqlmodel import Session
from app.infrastructure.database.repositories import SyncAnalysisRepository

from app.features.task_catalog import registry
from app.infrastructure.database.session import sync_engine
from app.models.analysis import Analysis
from app.infrastructure.storage.previews import detect_scale_um_per_px
from app.infrastructure.storage.results import locate_result_json, read_json

log = logging.getLogger(__name__)


class ExcelDownloadService:
    # ------------------------------------------------------------------ #
    # 列定义（来自记录所属族）
    # ------------------------------------------------------------------ #
    def get_available_columns(self, task_type: Optional[str] = None) -> Dict[str, str]:
        """按分析类型返回可导出的列（key -> 中文名）。"""
        return registry.columns_for(task_type)

    # ------------------------------------------------------------------ #
    # 读取并计算
    # ------------------------------------------------------------------ #
    def load_analysis_data(self, analysis_id: str, user_id: str, unit: str = "um",
                           scale: float = 500.0, task_type: Optional[str] = None) -> Dict[str, Any]:
        """Compatibility entry for scripts; HTTP workflows supply loaded records."""
        with Session(sync_engine) as session:
            record = SyncAnalysisRepository(session).get(analysis_id, user_id)
            if record is None:
                raise HTTPException(status_code=404, detail="分析记录不存在")
            return self.load_record_data(record, user_id, unit, scale, task_type)

    def load_record_data(self, analysis_record: Analysis, user_id: str, unit: str = "um",
                         scale: float = 500.0, task_type: Optional[str] = None) -> Dict[str, Any]:
        """Calculate export data from a record already scoped by the repository."""
        default_task_type = registry.normalize_task_type(None)
        task_type = registry.normalize_task_type(task_type)
        analysis_id = analysis_record.analysis_id
        try:
            original_file_path = analysis_record.original_file_path
            if not original_file_path:
                raise HTTPException(status_code=404, detail="原始文件路径不存在")

            record_task_type = analysis_record.task_type or default_task_type
            result_json_path = analysis_record.result_json_path

            original_filename = os.path.basename(original_file_path)
            sample_name_with_uuid = os.path.splitext(original_filename)[0]

            if '_' in sample_name_with_uuid and len(sample_name_with_uuid.split('_')[0]) == 36:
                sample_name = sample_name_with_uuid.split('_', 1)[1]
            else:
                sample_name = sample_name_with_uuid

            # 以记录自身的类型为准，避免调用方传错类型导致口径串台
            if record_task_type and record_task_type != task_type:
                log.warning(f"分析记录 {analysis_id} 的类型为 {record_task_type}，"
                            f"与请求的 {task_type} 不一致，以记录为准")
                task_type = registry.normalize_task_type(record_task_type)

            json_file_path = self._locate_result_json(result_json_path, user_id, sample_name)

            if not json_file_path:
                raise HTTPException(
                    status_code=404,
                    detail=f"分析结果文件不存在, 样本名称: {sample_name}, 用户目录: {user_id}"
                )

            analysis_data = read_json(json_file_path)

            base_info = {
                "filename": os.path.basename(json_file_path).replace('.json', '')
            }

            # 统一解析像素当量：优先从图内 500µm 比例尺自动识别，失败回退请求参数 scale。
            # 历史实现把 scale 写死为 500 µm/px（前端从不传该参数），会让面积虚高数万倍。
            spec = registry.get_task(task_type)
            k = detect_scale_um_per_px(original_file_path) if spec.auto_scale else None
            if k and k > 0:
                log.info(f"[{task_type}] 自动识别比例尺: {k:.4f} µm/px")
            else:
                k = float(scale) if scale and scale > 0 else 1.0
                log.warning(f"[{task_type}] 未识别到图内比例尺，回退请求参数 scale={k} µm/px")

            # 指标口径由记录所属的族决定（族自带算法，这里不做任何 if 判断）
            base_info.update(registry.compute_metrics(task_type, analysis_data, unit, k))
            return base_info

        except HTTPException:
            raise
        except Exception as e:
            log.error(f"加载分析数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"加载分析数据失败: {str(e)}")

    def _locate_result_json(self, result_json_path, user_id, sample_name):
        return locate_result_json(result_json_path, user_id, sample_name)

    def _validate_columns(self, selected_columns: List[str], task_type: str) -> Dict[str, str]:
        columns = self.get_available_columns(task_type)
        invalid_columns = [col for col in selected_columns if col not in columns]
        if invalid_columns:
            raise HTTPException(
                status_code=400,
                detail=f"无效的列选择（{registry.normalize_task_type(task_type)}）: {invalid_columns}"
            )
        return columns

    # ------------------------------------------------------------------ #
    # 生成 Excel
    # ------------------------------------------------------------------ #
    def generate_excel_data(self, analysis_data: Dict[str, Any], selected_columns: List[str],
                            task_type: Optional[str] = None) -> pd.DataFrame:
        columns = self._validate_columns(selected_columns, task_type)

        base_row = {}
        for col in selected_columns:
            if col in analysis_data:
                value = analysis_data[col]
                if isinstance(value, float):
                    base_row[col] = round(value, 4)
                else:
                    base_row[col] = value
            else:
                base_row[col] = "N/A"

        df = pd.DataFrame([base_row])

        column_mapping = {col: columns[col] for col in selected_columns}
        df = df.rename(columns=column_mapping)

        return df

    def create_excel_file(self, df: pd.DataFrame, filename: str = None) -> BytesIO:
        if filename is None:
            filename = f"{datetime.now().strftime('%Y.%m.%d_%H:%M')}.xlsx"

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='分析结果', index=False)

            worksheet = writer.sheets['分析结果']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        output.seek(0)
        return output

    def export_all_to_excel(self, analysis_data_list: List[Dict[str, Any]], selected_columns: List[str],
                            task_type: Optional[str] = None) -> BytesIO:
        columns = self._validate_columns(selected_columns, task_type)

        rows = []
        for analysis_data in analysis_data_list:
            row = {}
            for col in selected_columns:
                if col in analysis_data:
                    value = analysis_data[col]
                    if isinstance(value, float):
                        row[col] = round(value, 4)
                    else:
                        row[col] = value
                else:
                    row[col] = "N/A"
            rows.append(row)

        df = pd.DataFrame(rows)

        column_mapping = {col: columns[col] for col in selected_columns}
        df = df.rename(columns=column_mapping)

        filename = f"all_analysis_export_{len(analysis_data_list)}_samples_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return self.create_excel_file(df, filename)


excel_service = ExcelDownloadService()
