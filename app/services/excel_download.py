import os
import json
import pandas as pd
import logging
import math
from datetime import datetime
from typing import List, Dict, Any
from fastapi import HTTPException
from io import BytesIO
from sqlmodel import create_engine, Session, select
from app.core.config import settings
from app.models.analysis import Analysis

log = logging.getLogger(__name__)

class ExcelDownloadService:
    def __init__(self):
        self.available_columns = {
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
        
        self.unit_conversion = {
            "um": 1.0,
            "μm": 1.0,
            "mm": 1000.0,
            "cm": 10000.0
        }

    def get_available_columns(self) -> Dict[str, str]:
        return self.available_columns

    def load_analysis_data(self, analysis_id: str, user_id: str, unit: str = "um", scale: float = 500.0) -> Dict[str, Any]:
        try:
            sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
            sync_engine = create_engine(sync_db_url, echo=False)

            with Session(sync_engine) as session:
                statement = select(Analysis).where(Analysis.analysis_id == analysis_id)
                result = session.exec(statement)
                analysis_record = result.first()

                if not analysis_record:
                    raise HTTPException(status_code=404, detail="分析记录不存在")

                original_file_path = analysis_record.original_file_path
                if not original_file_path:
                    raise HTTPException(status_code=404, detail="原始文件路径不存在")

                original_filename = os.path.basename(original_file_path)
                sample_name_with_uuid = os.path.splitext(original_filename)[0]

                if '_' in sample_name_with_uuid and len(sample_name_with_uuid.split('_')[0]) == 36:
                    sample_name = sample_name_with_uuid.split('_', 1)[1]
                else:
                    sample_name = sample_name_with_uuid

            user_data_dir = os.path.join("app_storage", "user_data", user_id)
            if not os.path.exists(user_data_dir):
                raise HTTPException(status_code=404, detail="用户数据目录不存在")

            json_file_path = None

            sample_dir = os.path.join(user_data_dir, sample_name)
            if os.path.exists(sample_dir):
                for file in os.listdir(sample_dir):
                    if file.endswith('.json') and (sample_name in file or file.replace('.json', '') == sample_name):
                        json_file_path = os.path.join(sample_dir, file)
                        break

            if not json_file_path:
                for root, dirs, files in os.walk(user_data_dir):
                    for file in files:
                        if file.endswith('.json'):
                            full_path = os.path.join(root, file)
                            json_filename_without_ext = file.replace('.json', '')
                            if json_filename_without_ext == sample_name:
                                json_file_path = full_path
                                break
                    if json_file_path:
                        break

            if not json_file_path:
                for root, dirs, files in os.walk(user_data_dir):
                    for file in files:
                        if file.endswith('.json'):
                            full_path = os.path.join(root, file)
                            if sample_name in file:
                                json_file_path = full_path
                                break
                    if json_file_path:
                        break

            if not json_file_path:
                raise HTTPException(status_code=404, detail=f"分析结果文件不存在, 样本名称: {sample_name}, 用户目录: {user_data_dir}")

            with open(json_file_path, 'r', encoding='utf-8') as f:
                analysis_data = json.load(f)

            base_info = {
                "filename": os.path.basename(json_file_path).replace('.json', '')
            }

            shapes = analysis_data.get("shapes", [])

            large_tail_shapes = []
            small_tail_shapes = []
            out_shapes = []
            in_shapes = []

            for shape in shapes:
                label = shape.get("label", "unknown")
                area = self._calculate_shape_area(shape.get("points", []))

                if label == "big":
                    large_tail_shapes.append({"area": area})
                elif label == "small":
                    small_tail_shapes.append({"area": area})
                elif label == "out":
                    out_shapes.append({"area": area, "points": shape.get("points", [])})
                elif label == "in":
                    in_shapes.append({"area": area, "points": shape.get("points", [])})

            large_tail_count = len(large_tail_shapes)
            small_tail_count = len(small_tail_shapes)
            total_count = large_tail_count + small_tail_count

            large_tail_area_pixel = sum(shape["area"] for shape in large_tail_shapes)
            small_tail_area_pixel = sum(shape["area"] for shape in small_tail_shapes)

            stem_area_pixel = out_shapes[0]["area"] if out_shapes else 0
            cavity_area_pixel = in_shapes[0]["area"] if in_shapes else 0

            stem_diameter_pixel = self._calculate_diameter_from_area(stem_area_pixel)
            stem_perimeter_pixel = self._calculate_perimeter_from_area(stem_area_pixel)

            conversion_factor = self.unit_conversion.get(unit, 1.0)
            
            stem_diameter = stem_diameter_pixel * scale / conversion_factor
            stem_perimeter = stem_perimeter_pixel * scale / conversion_factor
            
            area_scale_factor = scale ** 2
            large_tail_area = large_tail_area_pixel * area_scale_factor / (conversion_factor ** 2)
            small_tail_area = small_tail_area_pixel * area_scale_factor / (conversion_factor ** 2)
            stem_area = stem_area_pixel * area_scale_factor / (conversion_factor ** 2)
            cavity_area = cavity_area_pixel * area_scale_factor / (conversion_factor ** 2)

            stem_cavity_area_diff = stem_area - cavity_area
            large_small_area_ratio = large_tail_area / small_tail_area if small_tail_area > 0 else 0
            large_small_count_ratio = large_tail_count / small_tail_count if small_tail_count > 0 else 0
            cavity_stem_area_ratio = cavity_area / stem_area if stem_area > 0 else 0
            small_count_perimeter_ratio = small_tail_count / stem_perimeter if stem_perimeter > 0 else 0
            large_count_perimeter_cavity_ratio = large_tail_count / (
                        stem_perimeter * stem_cavity_area_diff) if stem_perimeter > 0 and stem_cavity_area_diff > 0 else 0

            base_info.update({
                "largeTailCount": large_tail_count,
                "smallTailCount": small_tail_count,
                "totalCount": total_count,
                "largeTailArea": large_tail_area,
                "smallTailArea": small_tail_area,
                "stemDiameter": stem_diameter,
                "stemPerimeter": stem_perimeter,
                "cavityArea": cavity_area,
                "stemCavityAreaDiff": stem_cavity_area_diff,
                "largeSmallAreaRatio": large_small_area_ratio,
                "largeSmallCountRatio": large_small_count_ratio,
                "stemArea": stem_area,
                "cavityStemAreaRatio": cavity_stem_area_ratio,
                "smallCountPerimeterRatio": small_count_perimeter_ratio,
                "largeCountPerimeterCavityRatio": large_count_perimeter_cavity_ratio
            })

            return base_info

        except Exception as e:
            log.error(f"加载分析数据失败: {e}")
            raise HTTPException(status_code=500, detail=f"加载分析数据失败: {str(e)}")

    def _calculate_shape_area(self, points: List[List[float]]) -> float:
        if len(points) < 3:
            return 0.0

        area = 0.0
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]

        return abs(area) / 2.0

    def _calculate_diameter_from_area(self, area: float) -> float:
        if area <= 0:
            return 0.0
        return 2 * math.sqrt(area / math.pi)

    def _calculate_perimeter_from_area(self, area: float) -> float:
        if area <= 0:
            return 0.0
        return 2 * math.pi * math.sqrt(area / math.pi)

    def generate_excel_data(self, analysis_data: Dict[str, Any], selected_columns: List[str]) -> pd.DataFrame:
        invalid_columns = [col for col in selected_columns if col not in self.available_columns]
        if invalid_columns:
            raise HTTPException(status_code=400, detail=f"无效的列选择: {invalid_columns}")

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

        column_mapping = {col: self.available_columns[col] for col in selected_columns}
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

    def export_all_to_excel(self, analysis_data_list: List[Dict[str, Any]], selected_columns: List[str]) -> BytesIO:
        invalid_columns = [col for col in selected_columns if col not in self.available_columns]
        if invalid_columns:
            raise HTTPException(status_code=400, detail=f"无效的列选择: {invalid_columns}")

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

        column_mapping = {col: self.available_columns[col] for col in selected_columns}
        df = df.rename(columns=column_mapping)

        filename = f"all_analysis_export_{len(analysis_data_list)}_samples_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return self.create_excel_file(df, filename)

excel_service = ExcelDownloadService()