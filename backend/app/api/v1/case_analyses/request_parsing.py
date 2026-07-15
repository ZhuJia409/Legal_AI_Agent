from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from app.api.errors import document_parser_error_response, error_response
from app.core.config import Settings
from app.schemas.analysis import AnalysisRequest
from app.services.document_parser import DocumentParseError
from app.services.mineru_parser import DocumentParserProtocol

logger = logging.getLogger("legal_ai.api.case_analyses.request_parsing")


def _document_parser_error_response(exc: DocumentParseError) -> JSONResponse:
    return document_parser_error_response(
        exc,
        parse_error_message="案件材料解析失败，请检查文件后重试。",
    )


_error_response = error_response

_FILE_CONTENT_TYPES = {
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
        }
    ),
    ".md": frozenset(
        {
            "text/markdown",
            "text/x-markdown",
            "text/plain",
            "application/octet-stream",
        }
    ),
    ".txt": frozenset({"text/plain", "application/octet-stream"}),
}
_TEXT_EXTENSIONS = frozenset({".md", ".txt"})
_MULTIPART_BODY_OVERHEAD_BYTES = 1024 * 1024

ReceiveCallable = Callable[[], Awaitable[Message]]


class CaseUploadBodyTooLargeError(OSError):
    """multipart 请求体在表单落盘过程中超过服务端硬边界。"""


@dataclass(frozen=True, slots=True)
class ResolvedCaseContent:
    title: str | None
    content: str


async def _resolve_case_content(
    request: Request,
    document_parser: DocumentParserProtocol,
    settings: Settings,
) -> ResolvedCaseContent | JSONResponse:
    request_media_type = _normalize_media_type(request.headers.get("content-type"))
    if request_media_type == "application/json":
        return await _resolve_json_content(request, settings.case_analysis_max_content_chars)
    if request_media_type == "multipart/form-data":
        return await _resolve_uploaded_content(request, document_parser, settings)
    return _error_response(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        code="unsupported_media_type",
        message="仅支持 application/json 或 multipart/form-data 请求。",
    )


async def _resolve_json_content(
    request: Request,
    max_content_chars: int,
) -> ResolvedCaseContent | JSONResponse:
    try:
        data = await request.json()
    except ValueError:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_json",
            message="请求内容不是有效的 JSON。",
        )

    if not isinstance(data, dict):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="JSON 请求体必须是对象。",
        )
    raw_content = data.get("content")
    if raw_content is None or (isinstance(raw_content, str) and not raw_content.strip()):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="missing_content",
            message="请求体必须包含非空 content 字段。",
        )

    try:
        analysis_request = AnalysisRequest.model_validate(data)
    except ValidationError:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="请求字段格式无效。",
        )

    if analysis_request.content is None:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="missing_content",
            message="请求体必须包含非空 content 字段。",
        )
    content_error = _validate_resolved_content(
        analysis_request.content,
        max_content_chars=max_content_chars,
    )
    if content_error is not None:
        return content_error
    return ResolvedCaseContent(
        title=analysis_request.title,
        content=analysis_request.content,
    )


async def _resolve_uploaded_content(
    request: Request,
    document_parser: DocumentParserProtocol,
    settings: Settings,
) -> ResolvedCaseContent | JSONResponse:
    max_body_bytes = (
        settings.case_analysis_max_upload_bytes + _MULTIPART_BODY_OVERHEAD_BYTES
    )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_body_bytes:
                return _file_too_large_response()
        except ValueError:
            pass

    limited_request = Request(
        request.scope,
        _build_limited_receive(request.receive, max_body_bytes=max_body_bytes),
    )
    try:
        form = await limited_request.form(max_files=1, max_fields=4)
    except CaseUploadBodyTooLargeError:
        return _file_too_large_response()
    except StarletteHTTPException:
        # Starlette 仅用该异常表示 multipart 格式错误，未知编程异常继续向上暴露。
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_multipart",
            message="multipart 请求格式无效。",
        )

    file = form.get("file")
    if not isinstance(file, UploadFile):
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="missing_file",
            message="请上传案件材料文件。",
        )

    title = form.get("title")
    try:
        normalized_title = AnalysisRequest.model_validate(
            {"title": title, "content": "placeholder"}
        ).title
    except ValidationError:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="请求字段格式无效。",
        )

    filename = _safe_filename(file.filename or "uploaded-document")
    extension = _file_extension(filename)
    media_type = _normalize_media_type(file.content_type) or "application/octet-stream"
    if media_type not in _FILE_CONTENT_TYPES.get(extension, frozenset()):
        return _error_response(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="unsupported_file_type",
            message="案件材料仅支持 PDF、DOCX、MD 或 TXT 格式。",
        )

    try:
        source_bytes = await file.read(settings.case_analysis_max_upload_bytes + 1)
        await file.seek(0)
    except OSError as exc:
        logger.warning(
            "case_document_read_failed extension=%s error_type=%s",
            extension or "unknown",
            exc.__class__.__name__,
        )
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_parse_error",
            message="读取案件材料失败。",
        )

    if len(source_bytes) > settings.case_analysis_max_upload_bytes:
        return _file_too_large_response()
    if not source_bytes:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="empty_file",
            message="上传文件不能为空。",
        )

    if extension in _TEXT_EXTENSIONS:
        try:
            content = source_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_text_encoding",
                message="MD/TXT 文件必须使用 UTF-8 编码。",
            )
    else:
        try:
            content = await document_parser.parse(file)
        except DocumentParseError as exc:
            logger.warning(
                "case_document_parse_failed extension=%s error_type=%s",
                extension,
                exc.__class__.__name__,
            )
            return _document_parser_error_response(exc)

    if not isinstance(content, str):
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_parse_error",
            message="案件材料解析失败，请检查文件后重试。",
        )
    normalized_content = content.strip()
    content_error = _validate_resolved_content(
        normalized_content,
        max_content_chars=settings.case_analysis_max_content_chars,
    )
    if content_error is not None:
        return content_error
    return ResolvedCaseContent(title=normalized_title, content=normalized_content)


def _validate_resolved_content(
    content: str,
    *,
    max_content_chars: int,
) -> JSONResponse | None:
    if not content:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="empty_content",
            message="案件材料未包含可分析的正文。",
        )
    if len(content) > max_content_chars:
        return _error_response(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="content_too_long",
            message="案件材料正文超过服务端字符限制。",
        )
    return None


def _build_limited_receive(
    receive: ReceiveCallable,
    *,
    max_body_bytes: int,
) -> ReceiveCallable:
    received = 0

    async def limited_receive() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            body = message.get("body", b"")
            received += len(body)
            if received > max_body_bytes:
                raise CaseUploadBodyTooLargeError("multipart body exceeds limit")
        return message

    return limited_receive


def _file_too_large_response() -> JSONResponse:
    return _error_response(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        code="file_too_large",
        message="上传文件超过服务端大小限制。",
    )


def _normalize_media_type(value: str | None) -> str:
    if not value:
        return ""
    return value.partition(";")[0].strip().lower()


def _file_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[-1].lower()}"


def _safe_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", basename).strip()
    return cleaned[:255] or "uploaded-document"
