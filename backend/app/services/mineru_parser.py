import asyncio
import logging
import re
import time
from collections.abc import Callable
from io import BytesIO
from typing import Protocol
from zipfile import BadZipFile, ZipFile

import httpx
from fastapi import UploadFile

from app.services.document_parser import DocumentParseError

logger = logging.getLogger("legal_ai.services.mineru")

MINERU_DEFAULT_BASE_URL = "https://mineru.net"
MINERU_FILE_URLS_PATH = "/api/v4/file-urls/batch"
MINERU_EXTRACT_RESULTS_PATH = "/api/v4/extract-results/batch"

AsyncClientFactory = Callable[[], httpx.AsyncClient]


class DocumentParserProtocol(Protocol):
    async def parse(self, file: UploadFile) -> str:
        """Parse an uploaded document and return normalized markdown text."""


class MineruDocumentParser:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = MINERU_DEFAULT_BASE_URL,
        model_version: str = "vlm",
        poll_interval_seconds: float = 2,
        poll_timeout_seconds: float = 180,
        client_factory: AsyncClientFactory | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model_version = model_version
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self.client_factory = client_factory or self._default_client_factory

    async def parse(self, file: UploadFile) -> str:
        if not self.api_key:
            raise DocumentParseError("MINERU_API_KEY is not configured.")

        filename = file.filename or "uploaded-contract"
        started = time.monotonic()
        try:
            file_bytes = await file.read()
        except Exception as exc:
            raise DocumentParseError("读取上传文件失败。") from exc

        if not file_bytes:
            raise DocumentParseError("上传文件为空。")

        logger.info(
            "mineru_parse_started filename=%s bytes=%d model_version=%s",
            filename,
            len(file_bytes),
            self.model_version,
        )
        async with self.client_factory() as client:
            batch_id, upload_url = await self._create_upload_url(client, filename)
            logger.info("mineru_upload_url_created filename=%s batch_id=%s", filename, batch_id)
            await self._upload_file(client, upload_url, file_bytes)
            logger.info("mineru_upload_completed filename=%s batch_id=%s", filename, batch_id)
            zip_url = await self._poll_result(client, batch_id)
            zip_bytes = await self._download_zip(client, zip_url)

        text = _extract_full_markdown(zip_bytes)
        logger.info(
            "mineru_parse_completed filename=%s batch_id=%s content_length=%d elapsed=%.2fs",
            filename,
            batch_id,
            len(text),
            time.monotonic() - started,
        )
        return text

    def _default_client_factory(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=15.0),
            trust_env=False,
        )

    def _authorization_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _create_upload_url(
        self,
        client: httpx.AsyncClient,
        filename: str,
    ) -> tuple[str, str]:
        payload = {
            "files": [{"name": filename, "data_id": _safe_data_id(filename)}],
            "model_version": self.model_version,
        }
        data = await self._request_mineru_json(
            client,
            "POST",
            MINERU_FILE_URLS_PATH,
            json=payload,
        )

        batch_id = data.get("batch_id")
        upload_url = _first_upload_url(data)
        if not isinstance(batch_id, str) or not batch_id:
            raise DocumentParseError("MinerU 未返回 batch_id。")
        if not upload_url:
            raise DocumentParseError("MinerU 未返回文件上传地址。")
        return batch_id, upload_url

    async def _upload_file(
        self,
        client: httpx.AsyncClient,
        upload_url: str,
        file_bytes: bytes,
    ) -> None:
        try:
            response = await client.put(upload_url, content=file_bytes)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DocumentParseError("上传文件到 MinerU 预签名地址失败。") from exc

    async def _poll_result(self, client: httpx.AsyncClient, batch_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout_seconds
        path = f"{MINERU_EXTRACT_RESULTS_PATH}/{batch_id}"

        while time.monotonic() <= deadline:
            data = await self._request_mineru_json(client, "GET", path)
            result = _first_extract_result(data)
            state = str(result.get("state") or result.get("status") or "").lower()
            logger.info("mineru_poll_result batch_id=%s state=%s", batch_id, state or "unknown")

            if state in {"done", "success", "succeeded", "completed"}:
                zip_url = _first_non_empty(
                    result.get("full_zip_url"),
                    result.get("zip_url"),
                    result.get("result_url"),
                )
                if zip_url:
                    return zip_url
                raise DocumentParseError("MinerU 解析完成但未返回 full_zip_url。")

            if state in {"failed", "fail", "error"}:
                message = result.get("err_msg") or result.get("message") or "unknown error"
                raise DocumentParseError(f"MinerU 文档解析失败：{message}")

            await asyncio.sleep(self.poll_interval_seconds)

        raise DocumentParseError("MinerU 文档解析超时。")

    async def _download_zip(self, client: httpx.AsyncClient, zip_url: str) -> bytes:
        try:
            response = await client.get(zip_url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise DocumentParseError("下载 MinerU 解析结果失败。") from exc
        return response.content

    async def _request_mineru_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        **kwargs: object,
    ) -> dict[str, object]:
        url = f"{self.base_url}{path}"
        try:
            response = await client.request(
                method,
                url,
                headers=self._authorization_headers(),
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise DocumentParseError("调用 MinerU API 失败。") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            if response.is_error:
                raise DocumentParseError(
                    f"调用 MinerU API 失败（HTTP {response.status_code}）。"
                ) from exc
            raise DocumentParseError("MinerU API 返回内容不是有效 JSON。") from exc

        if response.is_error:
            raise DocumentParseError(
                f"调用 MinerU API 失败（HTTP {response.status_code}）："
                f"{_mineru_error_message(payload)}"
            )

        if not isinstance(payload, dict):
            raise DocumentParseError("MinerU API 返回结构无效。")

        code = payload.get("code")
        success = payload.get("success")
        if success is False or code not in (0, "0", None):
            raise DocumentParseError(f"MinerU API 返回错误：{_mineru_error_message(payload)}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise DocumentParseError("MinerU API 未返回 data 对象。")
        return data


def _first_upload_url(data: dict[str, object]) -> str | None:
    candidates = data.get("file_urls") or data.get("upload_urls") or data.get("files")
    if isinstance(candidates, str):
        return candidates
    if not isinstance(candidates, list) or not candidates:
        return None

    first = candidates[0]
    if isinstance(first, str):
        return first
    if isinstance(first, dict):
        return _first_non_empty(first.get("upload_url"), first.get("url"), first.get("file_url"))
    return None


def _safe_data_id(filename: str) -> str:
    data_id = re.sub(r"[^0-9A-Za-z_.-]+", "_", filename).strip("._-")
    return (data_id or "uploaded_contract")[:128]


def _mineru_error_message(payload: object) -> str:
    if not isinstance(payload, dict):
        return "unknown error"

    code = _first_non_empty(
        payload.get("msgCode"),
        payload.get("code"),
        payload.get("error_code"),
    )
    message = _first_non_empty(
        payload.get("msg"),
        payload.get("message"),
        payload.get("error"),
    )
    if code and message:
        return f"{code} {message}"
    return code or message or "unknown error"


def _first_extract_result(data: dict[str, object]) -> dict[str, object]:
    result = data.get("extract_result") or data.get("results") or data.get("files")
    if isinstance(result, dict):
        return result
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    raise DocumentParseError("MinerU API 未返回解析结果。")


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_full_markdown(zip_bytes: bytes) -> str:
    try:
        with ZipFile(BytesIO(zip_bytes)) as archive:
            markdown_names = [
                name
                for name in archive.namelist()
                if name.replace("\\", "/").endswith("/full.md") or name == "full.md"
            ]
            if not markdown_names:
                raise DocumentParseError("MinerU 解析结果中未找到 full.md。")
            content = archive.read(markdown_names[0])
    except BadZipFile as exc:
        raise DocumentParseError("MinerU 解析结果不是有效 zip 文件。") from exc

    text = content.decode("utf-8-sig").strip()
    if not text:
        raise DocumentParseError("MinerU full.md 内容为空。")
    return text
