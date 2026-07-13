from io import BytesIO
from typing import Protocol

import anyio
from minio import Minio
from minio.error import S3Error


class ObjectStorageReadError(RuntimeError):
    """对象存储读取失败，隐藏底层服务细节供业务层统一转换。"""


class ObjectStorageProtocol(Protocol):
    async def put_bytes(self, *, key: str, content: bytes, content_type: str) -> str:
        """Store bytes and return object key."""

    async def get_bytes(self, *, key: str) -> bytes:
        """Read the complete object as bytes."""


class MinioObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    async def put_bytes(self, *, key: str, content: bytes, content_type: str) -> str:
        await anyio.to_thread.run_sync(self._put_bytes_sync, key, content, content_type)
        return key

    async def get_bytes(self, *, key: str) -> bytes:
        try:
            return await anyio.to_thread.run_sync(self._get_bytes_sync, key)
        except Exception as exc:
            # 不向上层泄漏 bucket、endpoint 或 MinIO 的原始错误文本。
            raise ObjectStorageReadError("对象存储读取失败") from exc

    def _get_bytes_sync(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            # urllib3 响应必须显式关闭并释放连接，避免下载请求耗尽连接池。
            response.close()
            response.release_conn()

    def _put_bytes_sync(self, key: str, content: bytes, content_type: str) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self.client.put_object(
                self.bucket,
                key,
                BytesIO(content),
                length=len(content),
                content_type=content_type,
            )
        except S3Error:
            raise
