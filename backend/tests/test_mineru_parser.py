import logging
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest
from starlette.datastructures import UploadFile

from app.services import document_parser as document_parser_errors
from app.services.document_parser import DocumentParseError
from app.services.mineru_parser import MineruDocumentParser


def _docx_upload(content: str, *, filename: str = "contract.docx") -> UploadFile:
    buffer = BytesIO(content.encode("utf-8"))
    return UploadFile(
        filename=filename,
        file=buffer,
        headers={
            "content-type": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        },
    )


def _zip_with_full_markdown(markdown: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("outputs/full.md", markdown)
    return buffer.getvalue()


def test_document_parser_specialized_errors_keep_base_compatibility() -> None:
    assert hasattr(document_parser_errors, "DocumentParserConfigurationError")
    assert hasattr(document_parser_errors, "DocumentParserUpstreamError")
    assert issubclass(
        document_parser_errors.DocumentParserConfigurationError,
        DocumentParseError,
    )
    assert issubclass(
        document_parser_errors.DocumentParserUpstreamError,
        DocumentParseError,
    )


@pytest.mark.asyncio
async def test_mineru_parser_uploads_file_and_returns_full_markdown() -> None:
    calls: list[tuple[str, str]] = []
    zip_bytes = _zip_with_full_markdown("# Parsed Contract\n\nOffice IT procurement terms.")
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        calls.append((request.method, str(request.url)))

        if request.method == "POST" and request.url.path == "/api/v4/file-urls/batch":
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": [
                            {
                                "data_id": "contract",
                                "upload_url": "https://upload.local/contract.docx",
                            }
                        ],
                    },
                },
            )

        if request.method == "PUT" and str(request.url) == "https://upload.local/contract.docx":
            assert len(request.content) > 0
            return httpx.Response(200)

        if request.method == "GET" and request.url.path == "/api/v4/extract-results/batch/batch-1":
            poll_count += 1
            state = "running" if poll_count == 1 else "done"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "contract.docx",
                                "state": state,
                                "full_zip_url": "https://download.local/result.zip",
                            }
                        ]
                    },
                },
            )

        if request.method == "GET" and str(request.url) == "https://download.local/result.zip":
            return httpx.Response(200, content=zip_bytes)

        return httpx.Response(404, json={"code": 404, "msg": "unexpected request"})

    parser = MineruDocumentParser(
        api_key="test-token",
        base_url="https://mineru.net",
        poll_interval_seconds=0,
        poll_timeout_seconds=5,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    parsed_text = await parser.parse(_docx_upload("Original uploaded content."))

    assert parsed_text == "# Parsed Contract\n\nOffice IT procurement terms."
    assert calls == [
        ("POST", "https://mineru.net/api/v4/file-urls/batch"),
        ("PUT", "https://upload.local/contract.docx"),
        ("GET", "https://mineru.net/api/v4/extract-results/batch/batch-1"),
        ("GET", "https://mineru.net/api/v4/extract-results/batch/batch-1"),
        ("GET", "https://download.local/result.zip"),
    ]


@pytest.mark.asyncio
async def test_mineru_parser_returns_batch_zip_and_markdown_artifacts() -> None:
    zip_bytes = _zip_with_full_markdown("# Parsed Contract\n\nOffice IT procurement terms.")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v4/file-urls/batch":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": [{"upload_url": "https://upload.local/contract.docx"}],
                    },
                },
            )
        if request.method == "PUT" and str(request.url) == "https://upload.local/contract.docx":
            return httpx.Response(200)
        if request.method == "GET" and request.url.path == "/api/v4/extract-results/batch/batch-1":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": {
                            "state": "done",
                            "full_zip_url": "https://download.local/result.zip",
                        }
                    },
                },
            )
        if request.method == "GET" and str(request.url) == "https://download.local/result.zip":
            return httpx.Response(200, content=zip_bytes)
        return httpx.Response(404)

    parser = MineruDocumentParser(
        api_key="test-token",
        base_url="https://mineru.net",
        poll_interval_seconds=0,
        poll_timeout_seconds=5,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await parser.parse_result(_docx_upload("Original uploaded content."))

    assert result.batch_id == "batch-1"
    assert result.zip_bytes == zip_bytes
    assert result.markdown == "# Parsed Contract\n\nOffice IT procurement terms."


@pytest.mark.asyncio
async def test_mineru_parser_requires_api_key() -> None:
    parser = MineruDocumentParser(api_key="")

    with pytest.raises(
        document_parser_errors.DocumentParserConfigurationError,
        match="MINERU_API_KEY",
    ):
        await parser.parse(_docx_upload("Contract content."))


@pytest.mark.asyncio
async def test_mineru_parser_propagates_upload_read_programming_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = _docx_upload("Contract content.")

    async def raise_programming_error(size: int = -1) -> bytes:
        del size
        raise TypeError("programming bug")

    monkeypatch.setattr(upload, "read", raise_programming_error)
    parser = MineruDocumentParser(api_key="test-token")

    with pytest.raises(TypeError, match="programming bug"):
        await parser.parse_result(upload)


@pytest.mark.asyncio
async def test_mineru_parser_wraps_upload_read_io_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = _docx_upload("Contract content.")

    async def raise_io_error(size: int = -1) -> bytes:
        del size
        raise OSError("disk read failed")

    monkeypatch.setattr(upload, "read", raise_io_error)
    parser = MineruDocumentParser(api_key="test-token")

    with pytest.raises(DocumentParseError, match="读取上传文件失败"):
        await parser.parse_result(upload)


@pytest.mark.asyncio
async def test_mineru_parser_reports_upstream_authentication_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "traceId": "trace-1",
                "msgCode": "A0202",
                "msg": "user authenticate failed",
                "data": None,
                "success": False,
            },
        )

    parser = MineruDocumentParser(
        api_key="expired-token",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(DocumentParseError, match="A0202.*user authenticate failed"):
        await parser.parse(_docx_upload("Contract content."))


@pytest.mark.asyncio
async def test_mineru_parser_classifies_network_failure_as_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider network secret", request=request)

    parser = MineruDocumentParser(
        api_key="test-token",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(document_parser_errors.DocumentParserUpstreamError):
        await parser.parse(_docx_upload("Contract content."))


@pytest.mark.asyncio
async def test_mineru_logs_do_not_expose_upload_name_or_upstream_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_filename = "王某身份证合同.docx"
    sensitive_content = "不得进入日志的合同正文"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider raw secret", request=request)

    parser = MineruDocumentParser(
        api_key="test-token",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    caplog.set_level(logging.INFO, logger="legal_ai.services.mineru")

    with pytest.raises(document_parser_errors.DocumentParserUpstreamError):
        await parser.parse(
            _docx_upload(sensitive_content, filename=sensitive_filename)
        )

    assert sensitive_filename not in caplog.text
    assert sensitive_content not in caplog.text
    assert "provider raw secret" not in caplog.text
    assert "extension=.docx" in caplog.text


@pytest.mark.asyncio
async def test_mineru_parser_classifies_http_5xx_as_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"code": 503, "message": "provider internal secret"},
        )

    parser = MineruDocumentParser(
        api_key="test-token",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(document_parser_errors.DocumentParserUpstreamError):
        await parser.parse(_docx_upload("Contract content."))


@pytest.mark.asyncio
async def test_mineru_parser_classifies_poll_timeout_as_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-timeout",
                        "file_urls": [{"upload_url": "https://upload.local/file.docx"}],
                    },
                },
            )
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"extract_result": {"state": "running"}},
            },
        )

    parser = MineruDocumentParser(
        api_key="test-token",
        poll_interval_seconds=0,
        poll_timeout_seconds=0,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(document_parser_errors.DocumentParserUpstreamError):
        await parser.parse(_docx_upload("Contract content."))
