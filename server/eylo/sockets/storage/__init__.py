"""Typed storage socket exports."""

from eylo.sockets.storage.base import (
    StorageCapabilities,
    StorageFailure,
    StorageObjectTooLarge,
    StorageOperation,
    StorageOperationError,
    StorageRecovery,
    StorageVendorAdapter,
    StoredObject,
    UnsupportedStorageOperation,
)
from eylo.sockets.storage.factory import StorageFactory

__all__ = [
    "StorageCapabilities",
    "StorageFactory",
    "StorageFailure",
    "StorageObjectTooLarge",
    "StorageOperation",
    "StorageOperationError",
    "StorageRecovery",
    "StorageVendorAdapter",
    "StoredObject",
    "UnsupportedStorageOperation",
]
