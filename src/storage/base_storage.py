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
