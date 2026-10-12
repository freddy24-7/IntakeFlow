"""Uploaded files in Azure Blob Storage, behind the same Storage interface as the local folder."""

from typing import Any

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient


class BlobStorage:
    def __init__(self, container: Any, credential: Any = None) -> None:
        self._container = container
        self._credential = credential

    @classmethod
    def connect(cls, *, account_url: str, container: str) -> "BlobStorage":
        """Keyless: the app's managed identity in Azure, `az login` on a laptop."""
        credential = DefaultAzureCredential()
        return cls(ContainerClient(account_url, container, credential=credential), credential)

    async def save(self, key: str, content: bytes) -> None:
        await self._container.upload_blob(key, content, overwrite=True)

    async def load(self, key: str) -> bytes:
        download = await self._container.download_blob(key)
        content: bytes = await download.readall()
        return content

    async def close(self) -> None:
        await self._container.close()
        if self._credential is not None:
            await self._credential.close()
