"""Narrow storage protocols and an in-memory S3 fixture. No SDK/network IO."""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
import io
from threading import Lock
from typing import BinaryIO, Iterable, Protocol
import uuid

from src.recovery.runtime import digest, require


@dataclass(frozen=True)
class StorageIdentity:
    authority: str
    bucket: str
    resource_id: str
    aliases: tuple[str, ...] = ()
    mode: str = 'synthetic'


@dataclass(frozen=True)
class ListEntry:
    key: str
    size_bytes: int
    last_modified: str
    etag: str


@dataclass(frozen=True)
class Page:
    objects: tuple[ListEntry, ...]
    key_count: int
    is_truncated: bool
    next_token: str | None


@dataclass(frozen=True)
class Head:
    size_bytes: int
    last_modified: str
    etag: str
    metadata: dict[str, str]


@dataclass
class ReadResult:
    head: Head
    body: BinaryIO

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.body.close()


class ReadStorage(Protocol):
    identity: StorageIdentity

    def capabilities(self) -> frozenset[str]: ...
    def list_page(self, token: str | None = None) -> Page: ...
    def head_object(self, key: str) -> Head: ...
    def get_object(self, key: str, *, expected: Head) -> ReadResult: ...


class RestoreStorage(ReadStorage, Protocol):
    def put_if_absent(self, key: str, chunks: Iterable[bytes], *, size_bytes: int,
                      metadata: dict[str, str]) -> None: ...


class MetadataSource(Protocol):
    def snapshot(self) -> dict: ...


@dataclass
class SyntheticObject:
    payload: bytes
    metadata: dict[str, str] = field(default_factory=dict)
    last_modified: str = '2026-01-01T00:00:00Z'
    list_etag: str | None = None
    head_etag: str | None = None


class SyntheticStorage:
    """Small memory fixtures only; fixture mutation is not a cloud-write adapter.

    resource_id identifies the underlying bucket across endpoint/name aliases.
    LIST and HEAD ETags intentionally differ; GET uses HEAD's native validator.
    """
    def __init__(self, bucket='fixture-source', *, objects=None, page_size=17,
                 identity=None, capabilities=None):
        self.identity = identity or StorageIdentity('fixture-account', bucket, uuid.uuid4().hex)
        self.objects = deepcopy(objects or {})
        require(type(page_size) is int and page_size > 0, 'S3_INVALID_PAGE_SIZE')
        self.page_size = page_size
        self._capabilities = frozenset(capabilities if capabilities is not None else
                                       ('list', 'head', 'get', 'conditional_get', 'put_if_absent'))
        self.calls = Counter()
        self._lock = Lock()

    def capabilities(self):
        return self._capabilities

    def _allow(self, operation):
        self.calls[operation] += 1
        require(operation in self._capabilities, 'S3_STORAGE_ACCESS_DENIED')

    def _object(self, key):
        require(key in self.objects, 'S3_STORAGE_OBJECT_MISSING')
        return self.objects[key]

    def list_page(self, token=None):
        self._allow('list')
        require(token is None or (isinstance(token, str) and token.isdecimal()), 'S3_INVALID_PAGE_TOKEN')
        start = 0 if token is None else int(token)
        keys = sorted(self.objects)
        require(start <= len(keys), 'S3_INVALID_PAGE_TOKEN')
        selected = keys[start:start + self.page_size]
        rows = tuple(ListEntry(key, len(self.objects[key].payload), self.objects[key].last_modified,
                               self.objects[key].list_etag or 'list:' + digest(self.objects[key].payload)) for key in selected)
        end = start + len(rows)
        return Page(rows, len(rows), end < len(keys), str(end) if end < len(keys) else None)

    def head_object(self, key):
        self._allow('head')
        obj = self._object(key)
        return Head(len(obj.payload), obj.last_modified, obj.head_etag or 'head:' + digest(obj.payload), deepcopy(obj.metadata))

    def get_object(self, key, *, expected):
        self._allow('get')
        require('conditional_get' in self._capabilities, 'S3_CONDITIONAL_GET_UNSUPPORTED')
        actual = self.head_object(key)
        require(actual == expected, 'S3_SOURCE_PRECONDITION_FAILED')
        return ReadResult(actual, io.BytesIO(self._object(key).payload))

    def put_if_absent(self, key, chunks, *, size_bytes, metadata):
        self._allow('put_if_absent')
        with self._lock:
            require(key not in self.objects, 'S3_DESTINATION_COLLISION')
        raw = bytearray()
        for chunk in chunks:
            require(isinstance(chunk, bytes), 'S3_INVALID_STREAM')
            raw.extend(chunk)
            require(len(raw) <= min(size_bytes, 8 * 1024 * 1024), 'S3_SYNTHETIC_PAYLOAD_LIMIT')
        require(len(raw) == size_bytes, 'S3_DESTINATION_SIZE')
        with self._lock:
            require(key not in self.objects, 'S3_DESTINATION_COLLISION')
            self.objects[key] = SyntheticObject(bytes(raw), deepcopy(metadata))


class StaticMetadata:
    """Future read-only database adapters supply the same detached snapshot DTO."""
    def __init__(self, snapshot):
        self.value = deepcopy(snapshot)

    def snapshot(self):
        return deepcopy(self.value)
