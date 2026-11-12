from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings


class ObjectStore(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalObjectStore(ObjectStore):
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class S3ObjectStore(ObjectStore):
    def __init__(self):
        import boto3

        if not settings.S3_BUCKET:
            raise ValueError("S3_BUCKET is required")
        self.client = boto3.client("s3", endpoint_url=settings.S3_ENDPOINT_URL)

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=settings.S3_BUCKET, Key=key)
        with response["Body"] as body:
            return body.read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=settings.S3_BUCKET, Key=key)


def object_store() -> ObjectStore:
    if settings.OBJECT_STORE == "s3":
        return S3ObjectStore()
    if settings.OBJECT_STORE == "local":
        return LocalObjectStore(settings.OBJECT_STORE_PATH)
    raise ValueError("Unknown OBJECT_STORE")
