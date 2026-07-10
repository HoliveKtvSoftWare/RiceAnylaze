import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
import logging
from typing import List, Dict, Any
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.auth.core import fastapi_users
from app.models.user import UserTable
from app.auth.db import get_async_session
from app.models.analysis import Analysis
from app.services.excel_download import excel_service
import base64
from pydantic import BaseModel

class ExportRequest(BaseModel):
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0

log = logging.getLogger(__name__)

router = APIRouter()
current_active_user = fastapi_users.current_user(active=True)


@router.get("/columns")
async def get_export_columns():
    return {
        "available_columns": excel_service.get_available_columns(),
        "message": "可导出的列配置"
    }


@router.post("/summary")
async def export_all_analysis_to_excel(
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    try:
        selected_columns = request_data.selectedColumns
        unit = request_data.unit
        scale = request_data.scale
        log.info(f"用户 {user.id} 请求导出所有分析记录，选择的列: {selected_columns}，单位: {unit}，比例尺: {scale}")

        statement = select(Analysis).where(
            Analysis.user_id == user.id,
            Analysis.status == "completed"
        ).order_by(Analysis.created_at.desc())

        result = await db.execute(statement)
        all_analyses = result.scalars().all()

        if not all_analyses:
            raise HTTPException(status_code=404, detail="没有找到已完成的分析记录")

        log.info(f"找到 {len(all_analyses)} 个已完成的分析记录")

        valid_analysis_data = []
        for analysis in all_analyses:
            try:
                analysis_data = excel_service.load_analysis_data(str(analysis.analysis_id), str(user.id), unit, scale)
                valid_analysis_data.append(analysis_data)
                log.debug(f"成功加载分析数据: {analysis.analysis_id}")
            except Exception as e:
                log.warning(f"加载分析数据失败 {analysis.analysis_id}: {e}")
                continue

        if not valid_analysis_data:
            raise HTTPException(status_code=404, detail="没有成功加载任何分析数据")

        log.info(f"成功加载 {len(valid_analysis_data)} 个分析任务的数据")

        excel_file = excel_service.export_all_to_excel(valid_analysis_data, selected_columns)

        log.info(f"所有分析记录Excel文件生成成功，包含 {len(valid_analysis_data)} 个样本")

        return {
            "filename": f"{len(valid_analysis_data)}条记录_{datetime.now().strftime('%Y.%m.%d_%H:%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "total_samples": len(valid_analysis_data),
            "message": f"成功导出 {len(valid_analysis_data)} 个分析记录"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出所有分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"导出所有分析记录失败: {str(e)}")


@router.post("/{analysis_id}")
async def export_analysis_to_excel(
        analysis_id: str,
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    try:
        selected_columns = request_data.selectedColumns
        unit = request_data.unit
        scale = request_data.scale
        log.info(f"用户 {user.id} 请求导出分析结果 {analysis_id}，选择的列: {selected_columns}，单位: {unit}，比例尺: {scale}")

        statement = select(Analysis).where(
            Analysis.analysis_id == analysis_id,
            Analysis.user_id == user.id
        )

        result = await db.execute(statement)
        analysis = result.scalar_one_or_none()

        if not analysis:
            log.warning(f"分析记录 {analysis_id} 不存在或不属于用户 {user.id}")
            raise HTTPException(status_code=404, detail="分析记录不存在")

        if analysis.status != "completed":
            log.warning(f"分析记录 {analysis_id} 状态为 {analysis.status}，无法导出")
            raise HTTPException(status_code=400, detail="分析记录尚未完成，无法导出")

        analysis_data = excel_service.load_analysis_data(str(analysis.analysis_id), str(user.id), unit, scale)

        df = excel_service.generate_excel_data(analysis_data, selected_columns)

        excel_file = excel_service.create_excel_file(df)

        log.info(f"分析记录 {analysis_id} Excel文件生成成功")

        return {
            "filename": f"{analysis_id}_{datetime.now().strftime('%Y.%m.%d_%H:%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "message": "分析记录导出成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出分析记录时发生错误 {e}")
        raise HTTPException(status_code=500, detail=f"导出分析记录失败: {str(e)}")