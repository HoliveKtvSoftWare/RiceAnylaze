"""Storage path helpers shared by API and maintenance jobs."""

import logging
import os
import shutil
from typing import List, Optional

from app.core.config import settings
from app.models.analysis import Analysis
from app.infrastructure.storage.previews import preview_path_for

log = logging.getLogger(__name__)


def files_of_analysis(analysis: Analysis) -> List[str]:
    """Return generated and source files belonging to one analysis record."""
    files = [
        analysis.original_file_path,
        analysis.annotated_image_path,
        analysis.result_json_path,
    ]
    if analysis.original_file_path:
        files.append(preview_path_for(analysis.original_file_path))
    return [file_path for file_path in files if file_path]


def remove_files(paths: List[str]) -> None:
    """Best-effort removal of analysis files; one failure must not stop cleanup."""
    for file_path in paths:
        if not os.path.exists(file_path):
            continue
        try:
            os.remove(file_path)
            log.info("已删除文件: %s", file_path)
        except Exception as exc:  # noqa: BLE001
            log.error("删除文件 %s 时出错: %s", file_path, exc)


def path_to_static_url(path: Optional[str], base_url: str) -> Optional[str]:
    """Convert a storage path into a URL below the mounted static directory."""
    if not path:
        return None
    cleaned_path = path.replace('.\\', '').replace('./', '').replace('\\', '/')
    storage_base_path = settings.STORAGE_PATH.strip('.').strip('/').strip('\\') + '/'
    if cleaned_path.startswith(storage_base_path):
        relative_path = cleaned_path[len(storage_base_path):]
    else:
        log.warning("文件路径 '%s' 不在预期的存储根目录 '%s' 下", cleaned_path, storage_base_path)
        relative_path = cleaned_path
    return f"{base_url.rstrip('/')}/static/{relative_path.lstrip('/')}"


def original_filename(path: Optional[str]) -> str:
    """Recover the user-facing filename from a UUID-prefixed storage path."""
    if not path:
        return "未知文件名"
    basename = os.path.basename(path)
    parts = basename.split('_', 1)
    if len(parts) == 2 and len(parts[0]) == 36:
        return parts[1]
    return basename


def save_upload_file(source, destination: str) -> None:
    """Persist an uploaded binary stream; workflow owns error presentation."""
    with open(destination, "wb") as target:
        shutil.copyfileobj(source, target)
