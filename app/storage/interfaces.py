"""Where uploaded files live. A local folder now, Azure Blob Storage in stage 6."""

from typing import Protocol


class Storage(Protocol):
    async def save(self, key: str, content: bytes) -> None: ...

    async def load(self, key: str) -> bytes: ...
