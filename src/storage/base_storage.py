"""Base storage abstraction for interchangeable storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Abstract base class defining the contract for all storage backends.

    Subclasses must implement methods for reading, writing, inspecting,
    and enumerating files using standard path/prefix conventions.
    """

    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read and return the raw byte contents of a file.

        Args:
            path: Logical path to the file.

        Returns:
            bytes: The binary content of the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def write_file(self, path: str, content: bytes) -> None:
        """Write raw byte contents to a file at the specified path.

        Creates any necessary parent directories or namespaces if they do
        not already exist.

        Args:
            path: Logical path to destination file.
            content: Binary data to write.
        """
        raise NotImplementedError

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check whether a file exists at the given path.

        Args:
            path: Logical path to the file.

        Returns:
            bool: True if the file exists, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def list_files(self, prefix: str) -> list[str]:
        """List all file paths matching the given prefix.

        Args:
            prefix: Logical path prefix or directory path.

        Returns:
            list[str]: Sorted list of relative logical file paths matching the prefix.
        """
        raise NotImplementedError

    @abstractmethod
    def get_version_marker(self, path: str) -> str | None:
        """Return an opaque version identifier for a file if it exists, or None.

        For local storage, this can be formatted as f"{mtime_ns}:{size}".
        For S3, this can be the ETag or LastModified timestamp.

        Args:
            path: Logical path to the file.

        Returns:
            str | None: String version marker if file exists, else None.
        """
        raise NotImplementedError

    def read_file_range(self, path: str, start: int = 0, length: int | None = None) -> bytes:
        """Read a slice of raw byte contents of a file without loading the entire file into memory.

        Args:
            path: Logical path to the file.
            start: Starting byte offset (0-indexed).
            length: Maximum number of bytes to read, or None to read to end of file.

        Returns:
            bytes: The requested slice of binary content.
        """
        content = self.read_file(path)
        if length is not None:
            return content[start : start + length]
        return content[start:]

