from fastapi import status
from fastapi.responses import JSONResponse

from app.services.document_parser import (
    DocumentParseError,
    DocumentParserConfigurationError,
    DocumentParserUpstreamError,
)


def error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    """构造所有业务路由共用的受控错误 envelope。"""

    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def document_parser_error_response(
    exc: DocumentParseError,
    *,
    parse_error_message: str,
) -> JSONResponse:
    """按解析失败类型映射稳定状态码，同时保留业务域文案。"""

    if isinstance(exc, DocumentParserConfigurationError):
        return error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="document_parser_configuration_error",
            message="文档解析服务配置不可用，请联系管理员。",
        )
    if isinstance(exc, DocumentParserUpstreamError):
        return error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="document_parser_upstream_error",
            message="文档解析服务暂时不可用，请稍后重试。",
        )
    return error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="document_parse_error",
        message=parse_error_message,
    )
