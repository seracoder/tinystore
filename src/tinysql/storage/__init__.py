"""Storage backends for TinySQL."""

from .base import StorageBackend
from .json import JsonStorage

__all__ = ["JsonStorage", "StorageBackend"]
