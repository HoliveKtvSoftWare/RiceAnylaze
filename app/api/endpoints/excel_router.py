import uuid
import os
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from fastapi.responses import FileResponse
import logging
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.auth.core import fastapi_users
from app.models.user import UserTable
from app.auth.db import get_async_session
from app.models.analysis import Analysis
from app.services.excel_download import excel_service
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()
current_active_user = fastapi_users.current_user(active=True)

_FILENAME_UNIT_LABEL = {"um": "μm", "μm": "μm", "mm": "mm", "cm": "cm"}

_export_tasks: Dict[str, Dict[str, Any]] = {}
_export_tasks_lock = threading.Lock()


class ExportRequest(BaseModel):
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0


class AsyncExportRequest(ExportRequest):
    asyncMode: bool = False


class BatchExportRequest(BaseModel):
    analysisIds: Optional[List[str]] = None
    allCompleted: bool = False
    selectedColumns: List[str]
    unit: str = "um"
    scale: float = 500.0
    asyncMode: bool = False


@router.get("/columns")
async def get_export_columns():
    return {
        "available_columns": excel_service.get_available_columns(),
        "message": "可导出的列配置"
    }


@router.post("/summary")
async def export_all_analysis_to_excel(
        request_data: AsyncExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session),
        background_tasks: BackgroundTasks = None
):
    try:
        statement = select(Analysis).where(
            Analysis.user_id == user.id,
            Analysis.status == "completed"
        ).order_by(Analysis.created_at.desc())

        result = await db.execute(statement)
        all_records = result.scalars().all()

        if not all_records:
            raise HTTPException(status_code=404, detail="没有找到已完成的分析记录")

        if request_data.asyncMode:
            task_id = _submit_async_export(
                records=all_records,
                selected_columns=request_data.selectedColumns,
                unit=request_data.unit,
                scale=request_data.scale,
                prefix="summary",
                total=len(all_records),
                background_tasks=background_tasks,
            )
            return {
                "success": True,
                "message": f"已提交后台导出任务，共 {len(all_records)} 条记录",
                "taskId": task_id,
                "pollUrl": f"/api/excel/tasks/{task_id}",
                "downloadUrl": f"/api/excel/download/{task_id}",
            }

        file_path = _do_export(
            records=all_records,
            selected_columns=request_data.selectedColumns,
            unit=request_data.unit,
            scale=request_data.scale,
            prefix="summary",
        )

        time_str = datetime.now().strftime('%Y.%m.%d_%H%M%S')
        filename = f"{time_str}_{len(all_records)}条记录.xlsx"

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出所有分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.post("/batch")
async def export_batch_to_excel(
        request_data: BatchExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session),
        background_tasks: BackgroundTasks = None
):
    try:
        if request_data.allCompleted:
            statement = select(Analysis).where(
                Analysis.user_id == user.id,
                Analysis.status == "completed"
            ).order_by(Analysis.created_at.desc())
        elif request_data.analysisIds:
            statement = select(Analysis).where(
                Analysis.analysis_id.in_(request_data.analysisIds),
                Analysis.user_id == user.id,
                Analysis.status == "completed"
            )
        else:
            raise HTTPException(status_code=400, detail="请传入 analysisIds 或设置 allCompleted=true")

        result = await db.execute(statement)
        records = result.scalars().all()

        if not records:
            raise HTTPException(status_code=404, detail="没有找到有效的已完成分析记录")

        if request_data.asyncMode:
            task_id = _submit_async_export(
                records=records,
                selected_columns=request_data.selectedColumns,
                unit=request_data.unit,
                scale=request_data.scale,
                prefix="batch",
                total=len(records),
                background_tasks=background_tasks,
            )
            return {
                "success": True,
                "message": f"已提交后台导出任务，共 {len(records)} 条记录",
                "taskId": task_id,
                "pollUrl": f"/api/excel/tasks/{task_id}",
                "downloadUrl": f"/api/excel/download/{task_id}",
            }

        file_path = _do_export(
            records=records,
            selected_columns=request_data.selectedColumns,
            unit=request_data.unit,
            scale=request_data.scale,
            prefix="batch",
        )

        time_str = datetime.now().strftime('%Y.%m.%d_%H%M%S')
        filename = f"{time_str}_{len(records)}条记录.xlsx"

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"批量导出Excel时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"批量导出失败: {str(e)}")


@router.post("/{analysis_id}")
async def export_analysis_to_excel(
        analysis_id: str,
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    try:
        statement = select(Analysis).where(
            Analysis.analysis_id == analysis_id,
            Analysis.user_id == user.id
        )

        result = await db.execute(statement)
        analysis = result.scalar_one_or_none()

        if not analysis:
            raise HTTPException(status_code=404, detail="分析记录不存在")

        if analysis.status != "completed":
            raise HTTPException(status_code=400, detail="分析记录尚未完成，无法导出")

        analysis_data = excel_service.load_analysis_data_from_record(analysis, request_data.unit, request_data.scale)
        df = excel_service.generate_excel_data(analysis_data, request_data.selectedColumns)
        file_path = excel_service.create_excel_file(df)

        original_name = os.path.splitext(os.path.basename(analysis.original_file_path))[0]
        if '_' in original_name and len(original_name.split('_')[0]) == 36:
            original_name = original_name.split('_', 1)[1]
        time_str = datetime.now().strftime('%Y.%m.%d_%H%M%S')
        filename = f"{time_str}_{original_name}.xlsx"

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出分析记录时发生错误 {e}")
        raise HTTPException(status_code=500, detail=f"导出分析记录失败: {str(e)}")


@router.get("/tasks/{task_id}")
async def get_export_task_status(task_id: str):
    with _export_tasks_lock:
        task = _export_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    response = {
        "taskId": task_id,
        "status": task["status"],
        "total": task["total"],
        "progress": task["progress"],
        "createdAt": task["created_at"],
    }
    if task["status"] == "completed":
        response["downloadUrl"] = f"/api/excel/download/{task_id}"
        response["filename"] = task.get("filename")
    elif task["status"] == "failed":
        response["error"] = task.get("error", "未知错误")
    return response


@router.get("/download/{task_id}")
async def download_export_task(task_id: str):
    with _export_tasks_lock:
        task = _export_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"导出尚未完成，当前状态: {task['status']}")

    file_path = task["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件已丢失或被清理")

    return FileResponse(
        path=file_path,
        filename=task.get("filename") or os.path.basename(file_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _submit_async_export(
        records: list,
        selected_columns: List[str],
        unit: str,
        scale: float,
        prefix: str,
        total: int,
        background_tasks: Optional[BackgroundTasks] = None,
) -> str:
    task_id = str(uuid.uuid4())

    record_info_list = [
        {
            "analysis_id": str(r.analysis_id),
            "original_file_path": r.original_file_path,
            "result_json_path": r.result_json_path,
        }
        for r in records
    ]

    with _export_tasks_lock:
        _export_tasks[task_id] = {
            "status": "processing",
            "total": total,
            "progress": 0,
            "created_at": datetime.now().isoformat(),
            "file_path": None,
            "filename": None,
            "error": None,
        }

    kwargs = dict(
        task_id=task_id,
        record_info_list=record_info_list,
        selected_columns=selected_columns,
        unit=unit,
        scale=scale,
        prefix=prefix,
    )

    if background_tasks is not None:
        background_tasks.add_task(_run_export_worker, **kwargs)
    else:
        thread = threading.Thread(target=_run_export_worker, kwargs=kwargs, daemon=True)
        thread.start()

    return task_id


def _run_export_worker(
        task_id: str,
        record_info_list: list,
        selected_columns: List[str],
        unit: str,
        scale: float,
        prefix: str,
):
    try:
        from app.models.analysis import Analysis as _Analysis

        valid_data = []
        for idx, info in enumerate(record_info_list):
            record = _Analysis(
                analysis_id=uuid.UUID(info["analysis_id"]),
                original_file_path=info["original_file_path"],
                result_json_path=info["result_json_path"],
            )
            try:
                data = excel_service.load_analysis_data_from_record(record, unit, scale)
                valid_data.append(data)
            except Exception as e:
                log.warning(f"异步导出跳过记录 {info['analysis_id']}: {e}")

            with _export_tasks_lock:
                if task_id in _export_tasks:
                    _export_tasks[task_id]["progress"] = idx + 1

        if not valid_data:
            with _export_tasks_lock:
                _export_tasks[task_id]["status"] = "failed"
                _export_tasks[task_id]["error"] = "没有成功加载任何分析数据"
            return

        time_str = datetime.now().strftime('%Y.%m.%d_%H%M%S')
        filename = f"{time_str}_{len(valid_data)}条记录.xlsx"
        file_path = excel_service.export_all_to_excel(valid_data, selected_columns, filename)

        with _export_tasks_lock:
            if task_id in _export_tasks:
                _export_tasks[task_id]["status"] = "completed"
                _export_tasks[task_id]["file_path"] = file_path
                _export_tasks[task_id]["filename"] = filename
                _export_tasks[task_id]["progress"] = len(record_info_list)

        log.info(f"异步导出任务 {task_id} 完成: {file_path}（成功 {len(valid_data)}/{len(record_info_list)}）")

    except Exception as e:
        log.error(f"异步导出任务 {task_id} 失败: {e}")
        with _export_tasks_lock:
            if task_id in _export_tasks:
                _export_tasks[task_id]["status"] = "failed"
                _export_tasks[task_id]["error"] = str(e)


def _do_export(records: list, selected_columns: List[str], unit: str, scale: float, prefix: str = "export") -> str:
    valid_data = []
    for record in records:
        try:
            data = excel_service.load_analysis_data_from_record(record, unit, scale)
            valid_data.append(data)
        except Exception as e:
            log.warning(f"导出中跳过记录 {record.analysis_id}: {e}")
            continue

    if not valid_data:
        raise HTTPException(status_code=404, detail="没有成功加载任何分析数据")

    filename = f"{prefix}_{len(valid_data)}_samples_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    file_path = excel_service.export_all_to_excel(valid_data, selected_columns, filename)
    log.info(f"Excel 导出完成: {file_path}（成功 {len(valid_data)}/{len(records)}）")
    return file_path