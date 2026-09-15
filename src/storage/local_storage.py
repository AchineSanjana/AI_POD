"""Local filesystem implementation of the StorageBackend."""

from __future__ import annotations

from pathlib import Path

from src.storage.base_storage import StorageBackend
from src.utils.config import PROJECT_ROOT


class LocalStorage(StorageBackend):
    """Storage backend that reads and writes files to the local filesystem.

    By default, operations are rooted at ``PROJECT_ROOT``, matching the
    existing behavior of storing data under ``data/`` and models under ``models/``.

    Args:
        base_dir: Root directory for relative paths. Defaults to ``PROJECT_ROOT``.
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            self.base_dir = PROJECT_ROOT.resolve()
        else:
            self.base_dir = Path(base_dir).resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve a logical path against base_dir."""
        normalized = path.replace("\\", "/").strip()
        p = Path(normalized)
        if p.is_absolute():
            return p.resolve()
        # Strip any leading slashes for relative path resolution
        rel = normalized.lstrip("/")
        return (self.base_dir / rel).resolve()

    def read_file(self, path: str) -> bytes:
        """Read and return binary content of a file on the local filesystem."""
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(
                f"File not found: '{path}' (resolved to '{target}')"
            )
        return target.read_bytes()

    def write_file(self, path: str, content: bytes) -> None:
        """Write binary content to local file, creating parent directories."""
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def exists(self, path: str) -> bool:
        """Check whether a file exists at given path on local filesystem."""
        target = self._resolve(path)
        return target.is_file()

    def list_files(self, prefix: str) -> list[str]:
        """List all relative file paths matching the given prefix.

        Returns POSIX-style relative paths from the base directory.
        """
        clean_prefix = prefix.replace("\\", "/").strip().lstrip("/")
        if clean_prefix:
            target = (self.base_dir / clean_prefix).resolve()
        else:
            target = self.base_dir

        results: list[str] = []
        if target.is_dir():
            for file_path in target.rglob("*"):
                if file_path.is_file():
                    rel = file_path.relative_to(self.base_dir).as_posix()
                    results.append(rel)
        elif target.is_file():
            rel = target.relative_to(self.base_dir).as_posix()
            results.append(rel)
        elif target.parent.exists() and target.parent.is_dir():
            # Prefix might be a partial path matching file names
            for file_path in target.parent.rglob("*"):
                if file_path.is_file():
                    rel = file_path.relative_to(self.base_dir).as_posix()
                    if rel.startswith(clean_prefix):
                        results.append(rel)

        return sorted(results)
