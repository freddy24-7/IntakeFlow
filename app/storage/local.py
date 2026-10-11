"""File storage on the local disk, and an in-memory one for tests."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LocalStorage:
    root: Path

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("storage key points outside the storage folder")
        return path

    async def save(self, key: str, content: bytes) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    async def load(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)


@dataclass
class MemoryStorage:
    files: dict[str, bytes] = field(default_factory=dict)

    async def save(self, key: str, content: bytes) -> None:
        self.files[key] = content

    async def load(self, key: str) -> bytes:
        return self.files[key]
