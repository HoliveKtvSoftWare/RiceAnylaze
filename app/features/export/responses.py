# -*- coding: utf-8 -*-
"""导出下载响应的构造与文件名编码。

导出文件名带中文（如 ``茎秆_样本_20260926_202804_um.xlsx``）。HTTP 头只能是
latin-1，所以按 RFC 5987 同时给出 ASCII 回退名和 ``filename*=UTF-8''`` 形式。
前端 axios 是从 ``Content-Disposition`` 里取文件名的，因此 ``app/main.py``
的 CORS 需要 ``expose_headers=["Content-Disposition"]``，否则浏览器读不到。
"""

from __future__ import annotations

import io
import os
from urllib.parse import quote

from fastapi.responses import StreamingResponse

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_content_disposition(filename: str) -> str:
    """生成兼容中文名的 Content-Disposition。"""
    ascii_name = filename.encode("ascii", errors="ignore").decode("ascii") or "download"
    utf8_name = quote(filename)
    return "attachment; filename=\"{}\"; filename*=UTF-8''{}".format(ascii_name, utf8_name)


def stream_bytes(data: bytes, filename: str, media_type: str) -> StreamingResponse:
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers={
            "Content-Disposition": build_content_disposition(filename),
            "Content-Length": str(len(data)),
        },
    )


def stream_file(file_path: str, filename: str, media_type: str) -> StreamingResponse:
    """读盘后整体流出。

    导出文件是完整 xlsx，一次读完比 FileResponse 更容易保证 Content-Length
    与 Content-Disposition 一起下发（前端据此拿文件名）。
    """
    with open(file_path, "rb") as handle:
        data = handle.read()
    return stream_bytes(data, filename, media_type)


def xlsx_response(data: bytes, filename: str) -> StreamingResponse:
    return stream_bytes(data, filename, XLSX_MEDIA_TYPE)


def xlsx_file_response(file_path: str, filename: str) -> StreamingResponse:
    return stream_file(file_path, filename, XLSX_MEDIA_TYPE)


__all__ = [
    "XLSX_MEDIA_TYPE", "build_content_disposition",
    "stream_bytes", "stream_file", "xlsx_response", "xlsx_file_response",
]
