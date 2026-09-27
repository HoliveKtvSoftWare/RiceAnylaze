import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
from fastapi import HTTPException
from io import BytesIO
from sqlmodel import Session
from app.infrastructure.database.repositories import SyncAnalysisRepository

from app.features.task_catalog.catalog import normalize_task_type
from app.infrastructure.database.session import sync_engine
from app.models.analysis import Analysis
from app.domain.analysis.metrics import (
    AnalysisMetrics, LEAF_REGION_LABELS, LEAF_BUNDLE_LABELS,
    SCALE_BAR_UM, polygon_area, polygon_perimeter,
)
from app.infrastructure.storage.previews import detect_scale_um_per_px
from app.infrastructure.storage.results import locate_result_json, read_json

log = logging.getLogger(__name__)

class ExcelDownloadService(AnalysisMetrics):
    def __init__(self):
        # 茎秆截面指标（原有口径，保持不变）
        self.stem_columns = {
            "filename": "样本名称",
            "largeTailCount": "大维管束数目",
            "smallTailCount": "小维管束数目",
            "totalCount": "总维管束数目",
            "largeTailArea": "大维管束面积",
            "smallTailArea": "小维管束面积",
            "stemDiameter": "茎秆直径",
            "stemPerimeter": "茎秆周长",
            "cavityArea": "空腔面积",
            "stemCavityAreaDiff": "茎秆面积与空腔面积差值",
            "largeSmallAreaRatio": "大维管束面积与小维管束面积比值",
            "largeSmallCountRatio": "大维管束数目与小维管束数目比值",
            "stemArea": "茎秆面积",
            "cavityStemAreaRatio": "空腔面积与茎秆面积比值",
            "smallCountPerimeterRatio": "小维管束数目与茎秆周长比值",
            "largeCountPerimeterCavityRatio": "大维管束数目与茎秆周长与空腔面积差值比值"
        }

        # 剑叶指标：11 类标签可自洽计算的子集
        # 修正说明（相对参考脚本 4-30-2026侧脉代码.py）：
        #   1) 截面面积不再把完全位于主脉内部的空腔重复计入，另给出"组织净面积"；
        #   2) 周长改为直接使用多边形周长，不再做"合并周长减连接长度"的魔改，
        #      并按文档口径额外提供侧脉周长÷2。
        self.leaf_columns = {
            "filename": "样本名称",
            "scaleUmPerPx": "比例尺(µm/px)",
            "sectionArea": "截面面积(含腔)",
            "tissueArea": "组织净面积",
            "body1Area": "主脉面积",
            "body2Area": "空腔面积",
            "side1Area": "侧脉1面积",
            "side2Area": "侧脉2面积",
            "body1Perimeter": "主脉周长",
            "body2Perimeter": "空腔周长",
            "side1Perimeter": "侧脉1周长",
            "side2Perimeter": "侧脉2周长",
            "side1HalfPerimeter": "侧脉1周长÷2",
            "side2HalfPerimeter": "侧脉2周长÷2",
            "bodyBigCount": "主脉大维管束数目",
            "bodyBigTotalArea": "主脉大维管束总面积",
            "bodyBigAvgArea": "主脉大维管束平均面积",
            "bodySmallCount": "主脉小维管束数目",
            "bodySmallTotalArea": "主脉小维管束总面积",
            "bodySmallAvgArea": "主脉小维管束平均面积",
            "cavitySmallCount": "空腔小维管束数目",
            "cavitySmallTotalArea": "空腔小维管束总面积",
            "cavitySmallAvgArea": "空腔小维管束平均面积",
            "side1BigCount": "侧脉1大维管束数目",
            "side1BigTotalArea": "侧脉1大维管束总面积",
            "side1BigAvgArea": "侧脉1大维管束平均面积",
            "side1SmallCount": "侧脉1小维管束数目",
            "side1SmallTotalArea": "侧脉1小维管束总面积",
            "side1SmallAvgArea": "侧脉1小维管束平均面积",
            "side2BigCount": "侧脉2大维管束数目",
            "side2BigTotalArea": "侧脉2大维管束总面积",
            "side2BigAvgArea": "侧脉2大维管束平均面积",
            "side2SmallCount": "侧脉2小维管束数目",
            "side2SmallTotalArea": "侧脉2小维管束总面积",
            "side2SmallAvgArea": "侧脉2小维管束平均面积",
        }

        self.unit_conversion = {
            "um": 1.0,
            "μm": 1.0,
            "mm": 1000.0,
            "cm": 10000.0
        }

    # ------------------------------------------------------------------ #
    # 列定义
    # ------------------------------------------------------------------ #
    def get_available_columns(self, task_type: str = "stem") -> Dict[str, str]:
        """按分析类型返回可导出的列（key -> 中文名）。"""
        from app.features.task_catalog.catalog import get_task
        if get_task(task_type).metrics == "leaf":
            return self.leaf_columns
        return self.stem_columns

    def _columns_of(self, task_type: str = "stem") -> Dict[str, str]:
        return self.get_available_columns(task_type)

    # ------------------------------------------------------------------ #
    # 读取并计算
    # ------------------------------------------------------------------ #
    def load_analysis_data(self, analysis_id: str, user_id: str, unit: str = "um",
                           scale: float = 500.0, task_type: str = "stem") -> Dict[str, Any]:
        """Compatibility entry for scripts; HTTP workflows supply loaded records."""
        with Session(sync_engine) as session:
            record = SyncAnalysisRepository(session).get(analysis_id, user_id)
            if record is None:
                raise HTTPException(status_code=404, detail="分析记录不存在")
            return self.load_record_data(record, user_id, unit, scale, task_type)

    def load_record_data(self, analysis_record: Analysis, user_id: str, unit: str = "um",
                         scale: float = 500.0, task_type: str = "stem") -> Dict[str, Any]:
        """Calculate export data from a record already scoped by the repository."""
        task_type = normalize_task_type(task_type)
        analysis_id = analysis_record.analysis_id
        try:
            original_file_path = analysis_record.original_file_path
            if not original_file_path:
                raise HTTPException(status_code=404, detail="原始文件路径不存在")

            record_task_type = analysis_record.task_type or "stem"
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
                task_type = normalize_task_type(record_task_type)

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
            from app.features.task_catalog.catalog import get_task
            spec = get_task(task_type)
            k = detect_scale_um_per_px(original_file_path) if spec.auto_scale else None
            if k and k > 0:
                log.info(f"[{task_type}] 自动识别比例尺: {k:.4f} µm/px")
            else:
                k = float(scale) if scale and scale > 0 else 1.0
                log.warning(f"[{task_type}] 未识别到图内比例尺，回退请求参数 scale={k} µm/px")

            if spec.metrics == "leaf":
                metrics = self._load_leaf_metrics(analysis_data, unit, k)
            else:
                metrics = self._load_stem_metrics(analysis_data, unit, k)

            base_info.update(metrics)
            return base_info

        except HTTPException:
            raise
        except Exception as e:
            log.error(f"加载分析数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"加载分析数据失败: {str(e)}")

    def _locate_result_json(self, result_json_path, user_id, sample_name):
        return locate_result_json(result_json_path, user_id, sample_name)

    def _validate_columns(self, selected_columns: List[str], task_type: str) -> Dict[str, str]:
        columns = self._columns_of(task_type)
        invalid_columns = [col for col in selected_columns if col not in columns]
        if invalid_columns:
            raise HTTPException(
                status_code=400,
                detail=f"无效的列选择（{normalize_task_type(task_type)}）: {invalid_columns}"
            )
        return columns

    def generate_excel_data(self, analysis_data: Dict[str, Any], selected_columns: List[str],
                            task_type: str = "stem") -> pd.DataFrame:
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
                            task_type: str = "stem") -> BytesIO:
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
