from io import BytesIO
from typing import Protocol

import anyio
from minio import Minio
from minio.error import S3Error


class ObjectStorageProtocol(Protocol):
    async def put_bytes(self, *, key: str, content: bytes, content_type: str) -> str:
        """Store bytes and return object key."""


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
