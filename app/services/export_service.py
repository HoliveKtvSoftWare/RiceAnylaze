"""
JSON导出服务
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi.responses import StreamingResponse
import io
from urllib.parse import quote

log = logging.getLogger(__name__)


class ExportService:
    """JSON导出服务"""

    def get_json_data(self, json_path: str) -> Dict[str, Any]:
        """读取JSON文件内容"""
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def export_json_response(
        self,
        json_path: str,
        original_filename: Optional[str] = None
    ) -> StreamingResponse:
        """将JSON文件转换为可下载的响应，文件名格式为：导出时间_文件名.json"""
        data = self.get_json_data(json_path)
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        if original_filename is None:
            original_filename = os.path.basename(json_path)

        name_without_ext = os.path.splitext(original_filename)[0]
        if '_' in name_without_ext and len(name_without_ext.split('_')[0]) == 36:
            name_without_ext = name_without_ext.split('_', 1)[1]

        time_str = datetime.now().strftime('%Y.%m.%d_%H%M%S')
        filename = f"{time_str}_{name_without_ext}.json"

        ascii_name = filename.encode('ascii', errors='ignore').decode('ascii') or 'download'
        utf8_name = quote(filename)
        content_disposition = f"attachment; filename={ascii_name}; filename*=UTF-8''{utf8_name}"

        return StreamingResponse(
            io.BytesIO(json_str.encode('utf-8')),
            media_type="application/json",
            headers={
                "Content-Disposition": content_disposition,
                "Content-Length": str(len(json_str))
            }
        )

    def get_json_statistics(self, json_path: str) -> Dict[str, Any]:
        """获取JSON文件的统计信息"""
        try:
            data = self.get_json_data(json_path)
            file_stat = os.stat(json_path)

            return {
                'filename': os.path.basename(json_path),
                'file_size': file_stat.st_size,
                'file_size_human': self._format_size(file_stat.st_size),
                'modified_time': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                'shapes_count': len(data.get('shapes', [])),
                'labels': self._extract_labels(data),
                'image_width': data.get('imageWidth', 0),
                'image_height': data.get('imageHeight', 0),
            }
        except Exception as e:
            return {'error': str(e)}

    def _extract_labels(self, data: Dict) -> Dict[str, int]:
        """提取标签统计"""
        label_counts = {}
        for shape in data.get('shapes', []):
            label = shape.get('label', 'unknown')
            label_counts[label] = label_counts.get(label, 0) + 1
        return label_counts

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"


export_service = ExportService()