"""Version 2 S3 archive format with synthetic and explicit live collection scopes.

Keys are index data, never paths. No S3, Docker or environment IO occurs here.
Callers supply an in-memory 32-byte key and bounded streams. Database v1 is untouched.
"""
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.recovery.archive import exclusive_write, private_directory
from src.recovery.runtime import RecoveryError, digest, encoded, require

PROFILE = 's3-current-objects'
SCHEMA_VERSION = 2
MAGIC = b'FDPS302\x00'
OVERHEAD = len(MAGIC) + 12 + 16
MAX_CHUNK = 64 * 1024 * 1024
MAX_INDEX = 8 * 1024 * 1024
MAX_OBJECTS = 10000
MAX_CHUNKS = 20000
KDF_INFO = b'football-data-platform/s3-current-objects/v2'
CORE_FIELDS = {'profile', 'schema_version', 'scope', 'session_id', 'salt',
               'cipher', 'kdf', 'chunk_size', 'expected_objects'}
ENVELOPE_FIELDS = CORE_FIELDS | {'state', 'index_size', 'index_sha256', 'authentication'}


def _safe(function):
    """Public boundaries expose fixed error codes, never paths, keys or payloads."""
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except RecoveryError:
            raise
        except Exception:
            raise RecoveryError('S3_ARCHIVE_OPERATION_FAILED') from None
    return call


def _integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'S3_DUPLICATE_JSON_FIELD')
            result[key] = value
        return result

    def invalid(_):
        raise RecoveryError('S3_INVALID_JSON')

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError):
        raise RecoveryError('S3_INVALID_JSON') from None


def _no_links(path):
    # Includes Windows junctions/reparse points on Python 3.10 as well as symlinks.
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            require(not stat.S_ISLNK(info.st_mode)
                    and not (getattr(info, 'st_file_attributes', 0) & 0x400), 'S3_LINK_REFUSED')


def _directory(path):
    path = Path(path).absolute()
    require('..' not in path.parts, 'S3_PATH_TRAVERSAL')
    _no_links(path)
    require(path.is_dir(), 'S3_DIRECTORY_REQUIRED')
    return path


def _file(directory, name):
    require(name in ('session.json', 'manifest.json', 'index.json.enc', 'aborted.json')
            or re.fullmatch(r'object-[0-9]{8}-chunk-[0-9]{8}\.enc', name) is not None,
            'S3_UNSAFE_ARTIFACT_PATH')
    path = directory / name
    _no_links(path)
    if path.exists():
        info = path.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'S3_UNSAFE_ARTIFACT_FILE')
    return path


def _read(directory, name, limit, expected=None):
    path = _file(directory, name)
    require(path.is_file(), 'S3_ARTIFACT_MISSING')
    size = path.stat().st_size
    require(size <= limit and (expected is None or size == expected), 'S3_ARTIFACT_SIZE')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) == size, 'S3_ARTIFACT_SIZE')
    return raw


def _write(directory, name, raw):
    exclusive_write(_file(directory, name), raw)


def _keys(master_key, core):
    require(isinstance(master_key, bytes) and len(master_key) == 32, 'S3_INVALID_MASTER_KEY')
    material = HKDF(algorithm=hashes.SHA256(), length=96,
                    salt=bytes.fromhex(core['salt']), info=KDF_INFO).derive(master_key)
    return material[:32], material[32:64], material[64:]


def _aad(core, role, item=None, number=None):
    context = {'core': core, 'role': role}
    if item is not None:
        context.update(object_id=item['object_id'], key=item['key'], size_bytes=item['size_bytes'], chunk=number)
    return encoded(context)


def _decrypt(raw, key, aad):
    require(len(raw) >= OVERHEAD and raw.startswith(MAGIC), 'S3_CIPHERTEXT_FORMAT')
    try:
        return AESGCM(key).decrypt(raw[8:20], raw[20:], aad)
    except InvalidTag:
        raise RecoveryError('S3_GCM_AUTHENTICATION_FAILED') from None


def _metadata(value):
    require(isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str)
            for k, v in value.items()), 'S3_INVALID_METADATA')
    require(len(encoded(value)) <= 65536, 'S3_METADATA_TOO_LARGE')


def _object_key(key):
    require(isinstance(key, str) and 0 < len(key.encode('utf-8')) <= 1024, 'S3_INVALID_OBJECT_KEY')


class S3ArchiveWriter:
    """Exclusive new session; use as a context manager. Keys are not persisted.

    add_object(key, stream, size_bytes=..., metadata={...}) reads at most chunk_size
    bytes per request. seal() re-reads/decrypts everything before publishing SEALED.
    Any failure aborts the session; retry in a NEW session, never resume this one.
    """

    @_safe
    def __init__(self, parent, master_key, *, expected_objects, chunk_size=MAX_CHUNK,
                 scope='synthetic-local', permission_guard=None):
        require(_integer(expected_objects, maximum=MAX_OBJECTS), 'S3_INVALID_OBJECT_COUNT')
        require(_integer(chunk_size, 1, MAX_CHUNK), 'S3_INVALID_CHUNK_SIZE')
        require(isinstance(master_key, bytes) and len(master_key) == 32, 'S3_INVALID_MASTER_KEY')
        require(scope in ('synthetic-local', 'live-current-objects'), 'S3_ARCHIVE_SCOPE')
        require(scope != 'live-current-objects' or callable(permission_guard), 'S3_LIVE_PERMISSION_GUARD_REQUIRED')
        parent = _directory(parent)
        session = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
        self.directory = parent / session
        self.directory.mkdir(mode=0o700)  # No exist_ok: a collision never reuses artifacts.
        private_directory(self.directory)
        self.permission_guard = permission_guard
        if permission_guard:
            permission_guard(self.directory, initialize=True)
        self.core = {'profile': PROFILE, 'schema_version': SCHEMA_VERSION, 'scope': scope,
                     'session_id': session, 'salt': os.urandom(32).hex(), 'cipher': 'AES-256-GCM',
                     'kdf': 'HKDF-SHA256', 'chunk_size': chunk_size, 'expected_objects': expected_objects}
        self.data_key, self.index_key, self.mac_key = _keys(master_key, self.core)
        self.objects, self.seen = [], set()
        self.counter, self.index_budget = 0, 0
        self.state = 'OPEN'
        _write(self.directory, 'session.json', encoded(self.core))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.state != 'SEALED':
            self.abort()

    def abort(self):
        """Keep incomplete evidence; no cleanup, overwrite or key-file IO."""
        if self.state == 'SEALED':
            return
        self.state = 'ABORTED'
        try:
            _write(self.directory, 'aborted.json', encoded({'state': 'ABORTED'}))
        except OSError:
            pass  # Missing SEALED manifest already makes this session unusable.

    @_safe
    def add_object(self, key, stream, *, size_bytes, metadata=None):
        try:
            require(self.state == 'OPEN', 'S3_SESSION_NOT_OPEN')
            _object_key(key)
            require(key not in self.seen, 'S3_DUPLICATE_OBJECT_KEY')
            require(_integer(size_bytes), 'S3_INVALID_OBJECT_SIZE')
            require(len(self.objects) < self.core['expected_objects'], 'S3_OBJECT_COUNT_MISMATCH')
            metadata = {} if metadata is None else dict(metadata)
            _metadata(metadata)
            item = {'object_id': len(self.objects) + 1, 'key': key, 'size_bytes': size_bytes,
                    'metadata': metadata, 'chunks': []}
            self.index_budget += len(encoded(item))
            require(self.index_budget <= MAX_INDEX, 'S3_INDEX_TOO_LARGE')
            total_hash, remaining = hashlib.sha256(), size_bytes
            while remaining or not item['chunks']:
                wanted = min(remaining, self.core['chunk_size'])
                plain = bytearray()
                while len(plain) < wanted:
                    part = stream.read(wanted - len(plain))
                    require(isinstance(part, bytes) and 0 < len(part) <= wanted - len(plain), 'S3_SOURCE_TRUNCATED_OR_INVALID')
                    plain.extend(part)
                plain = bytes(plain)
                total_hash.update(plain)
                number = len(item['chunks']) + 1
                name = f"object-{item['object_id']:08d}-chunk-{number:08d}.enc"
                require(self.counter < MAX_CHUNKS, 'S3_TOO_MANY_CHUNKS')
                nonce = b'\x00' * 4 + self.counter.to_bytes(8, 'big')
                self.counter += 1
                raw = MAGIC + nonce + AESGCM(self.data_key).encrypt(nonce, plain, _aad(self.core, 'chunk', item, number))
                _write(self.directory, name, raw)
                chunk = {'file': name, 'size_bytes': len(plain), 'sha256': digest(plain),
                         'ciphertext_size': len(raw), 'ciphertext_sha256': digest(raw)}
                self.index_budget += len(encoded(chunk))
                require(self.index_budget <= MAX_INDEX, 'S3_INDEX_TOO_LARGE')
                item['chunks'].append(chunk)
                remaining -= len(plain)
            require(stream.read(1) == b'', 'S3_SOURCE_EXCEEDS_DECLARED_SIZE')
            item['sha256'] = total_hash.hexdigest()
            self.objects.append(item)
            self.seen.add(key)
        except BaseException:
            self.abort()
            raise

    @_safe
    def verify_pending(self):
        """Readback current data chunks before external consistency fences/seal.

        Does not create an index, publish SEALED or require all expected objects
        yet (a workflow can still append its authenticated evidence object).
        """
        try:
            require(self.state == 'OPEN', 'S3_SESSION_NOT_OPEN')
            if self.permission_guard:
                self.permission_guard(self.directory)
            require(_json(_read(self.directory, 'session.json', 65536)) == self.core, 'S3_SESSION_HEADER_MISMATCH')
            names = {'session.json'} | {c['file'] for item in self.objects for c in item['chunks']}
            require({p.name for p in self.directory.iterdir()} == names, 'S3_ARTIFACT_SET_MISMATCH')
            return S3Archive(self.directory, self.core, {'objects': self.objects}, self.data_key).verify()
        except BaseException:
            self.abort()
            raise

    @_safe
    def seal(self):
        try:
            require(self.state == 'OPEN', 'S3_SESSION_NOT_OPEN')
            require(len(self.objects) == self.core['expected_objects'], 'S3_OBJECT_COUNT_MISMATCH')
            index = {'objects': self.objects}
            plain = encoded(index)
            require(len(plain) <= MAX_INDEX, 'S3_INDEX_TOO_LARGE')
            nonce = b'\xff' * 4 + b'\x00' * 8  # Separate index key; never reused in a session.
            raw = MAGIC + nonce + AESGCM(self.index_key).encrypt(nonce, plain, _aad(self.core, 'index'))
            _write(self.directory, 'index.json.enc', raw)
            envelope = {**self.core, 'state': 'SEALED', 'index_size': len(raw), 'index_sha256': digest(raw)}
            # Verify bytes on disk, not the writer's in-memory plaintext/index.
            verified = _load(self.directory, self.core, envelope, self.data_key, self.index_key, sealed=False)
            verified.verify()
            if self.permission_guard:
                self.permission_guard(self.directory)
            envelope['authentication'] = hmac.new(self.mac_key, encoded(envelope), hashlib.sha256).hexdigest()
            _write(self.directory, 'manifest.json', encoded(envelope))
            self.state = 'SEALED'
            return verified.summary()
        except BaseException:
            self.abort()
            raise


def _validate_core(core):
    require(set(core) == CORE_FIELDS, 'S3_CORE_FIELDS')
    require(core['profile'] == PROFILE and type(core['schema_version']) is int
            and core['schema_version'] == 2
            and core['scope'] in ('synthetic-local', 'live-current-objects'), 'S3_PROFILE_OR_VERSION')
    require(isinstance(core['session_id'], str) and re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{32}', core['session_id'])
            is not None and _sha(core['salt']), 'S3_SESSION_OR_SALT')
    require(core['cipher'] == 'AES-256-GCM' and core['kdf'] == 'HKDF-SHA256', 'S3_CRYPTO_SUITE')
    require(_integer(core['chunk_size'], 1, MAX_CHUNK)
            and _integer(core['expected_objects'], maximum=MAX_OBJECTS), 'S3_CORE_LIMITS')


def _load(directory, core, envelope, data_key, index_key, *, sealed):
    require(not (directory / 'aborted.json').exists(), 'S3_SESSION_ABORTED')
    require(_json(_read(directory, 'session.json', 65536)) == core, 'S3_SESSION_HEADER_MISMATCH')
    require(_integer(envelope['index_size'], OVERHEAD, MAX_INDEX + OVERHEAD)
            and _sha(envelope['index_sha256']), 'S3_INDEX_DESCRIPTOR')
    raw = _read(directory, 'index.json.enc', MAX_INDEX + OVERHEAD, envelope['index_size'])
    require(digest(raw) == envelope['index_sha256'], 'S3_INDEX_CHECKSUM')
    index = _json(_decrypt(raw, index_key, _aad(core, 'index')))
    require(isinstance(index, dict) and set(index) == {'objects'} and isinstance(index['objects'], list), 'S3_INDEX_SCHEMA')
    require(len(index['objects']) == core['expected_objects'], 'S3_OBJECT_COUNT_MISMATCH')
    names = {'session.json', 'index.json.enc'} | ({'manifest.json'} if sealed else set())
    seen, count = set(), 0
    for ordinal, item in enumerate(index['objects'], 1):
        require(isinstance(item, dict) and set(item) == {'object_id', 'key', 'size_bytes', 'sha256', 'metadata', 'chunks'}, 'S3_OBJECT_SCHEMA')
        require(type(item['object_id']) is int and item['object_id'] == ordinal, 'S3_OBJECT_ORDER')
        _object_key(item['key'])
        require(item['key'] not in seen, 'S3_DUPLICATE_OBJECT_KEY')
        seen.add(item['key'])
        _metadata(item['metadata'])
        require(_integer(item['size_bytes']) and _sha(item['sha256']) and isinstance(item['chunks'], list), 'S3_OBJECT_DESCRIPTOR')
        n = max(1, (item['size_bytes'] + core['chunk_size'] - 1) // core['chunk_size'])
        require(len(item['chunks']) == n, 'S3_CHUNK_COUNT')
        for number, chunk in enumerate(item['chunks'], 1):
            count += 1
            require(count <= MAX_CHUNKS, 'S3_TOO_MANY_CHUNKS')
            require(isinstance(chunk, dict) and set(chunk) == {'file', 'size_bytes', 'sha256', 'ciphertext_size', 'ciphertext_sha256'}, 'S3_CHUNK_SCHEMA')
            name = f'object-{ordinal:08d}-chunk-{number:08d}.enc'
            require(chunk['file'] == name, 'S3_UNSAFE_ARTIFACT_PATH')
            size = min(core['chunk_size'], max(0, item['size_bytes'] - (number - 1) * core['chunk_size']))
            require(type(chunk['size_bytes']) is int and chunk['size_bytes'] == size
                    and type(chunk['ciphertext_size']) is int and chunk['ciphertext_size'] == size + OVERHEAD
                    and _sha(chunk['sha256']) and _sha(chunk['ciphertext_sha256']), 'S3_CHUNK_DESCRIPTOR')
            names.add(name)
    require({p.name for p in directory.iterdir()} == names, 'S3_ARTIFACT_SET_MISMATCH')
    return S3Archive(directory, core, index, data_key)


class S3Archive:
    """Verified format reader; object index is sensitive, summary is whitelisted."""
    def __init__(self, directory, core, index, data_key):
        self.directory, self.core, self.index, self._data_key = directory, core, index, data_key

    def _chunks(self, item):
        whole = hashlib.sha256()
        for number, chunk in enumerate(item['chunks'], 1):
            raw = _read(self.directory, chunk['file'], self.core['chunk_size'] + OVERHEAD, chunk['ciphertext_size'])
            require(digest(raw) == chunk['ciphertext_sha256'], 'S3_CIPHERTEXT_CHECKSUM')
            plain = _decrypt(raw, self._data_key, _aad(self.core, 'chunk', item, number))
            require(len(plain) == chunk['size_bytes'] and digest(plain) == chunk['sha256'], 'S3_PLAINTEXT_CHECKSUM')
            whole.update(plain)
            yield plain
        require(whole.hexdigest() == item['sha256'], 'S3_OBJECT_CHECKSUM')

    def iter_object_chunks(self, object_id):
        """Bounded verified plaintext iterator; caller must consume it completely."""
        try:
            require(_integer(object_id, 1, len(self.index['objects'])), 'S3_INVALID_OBJECT_ID')
            yield from self._chunks(self.index['objects'][object_id - 1])
        except RecoveryError:
            raise
        except Exception:
            raise RecoveryError('S3_ARCHIVE_OPERATION_FAILED') from None

    @_safe
    def verify(self):
        for item in self.index['objects']:
            for _ in self._chunks(item):
                pass
        return self.summary()

    def summary(self):
        return {'profile': PROFILE, 'schema_version': 2, 'session_id': self.core['session_id'],
                'scope': 'SYNTHETIC_LOCAL_ARCHIVE' if self.core['scope'] == 'synthetic-local'
                         else 'LIVE_CURRENT_OBJECTS_ARCHIVE', 'objects': len(self.index['objects']),
                'bytes': sum(item['size_bytes'] for item in self.index['objects']),
                'chunks': sum(len(item['chunks']) for item in self.index['objects']),
                'live_s3_backup_verified': False, 'remote_s3_restore_verified': False}


@_safe
def verify_archive(directory, master_key):
    directory = _directory(directory)
    envelope = _json(_read(directory, 'manifest.json', 65536))
    require(isinstance(envelope, dict) and set(envelope) == ENVELOPE_FIELDS, 'S3_MANIFEST_SCHEMA')
    core = {field: envelope[field] for field in CORE_FIELDS}
    _validate_core(core)
    data_key, index_key, mac_key = _keys(master_key, core)
    unsigned = {k: v for k, v in envelope.items() if k != 'authentication'}
    require(_sha(envelope['authentication']) and hmac.compare_digest(envelope['authentication'],
            hmac.new(mac_key, encoded(unsigned), hashlib.sha256).hexdigest()), 'S3_MANIFEST_AUTHENTICATION_FAILED')
    require(envelope['state'] == 'SEALED', 'S3_SESSION_NOT_SEALED')
    archive = _load(directory, core, envelope, data_key, index_key, sealed=True)
    archive.verify()
    return archive


@_safe
def inspect_archive(directory, master_key):
    """Authenticate and verify before returning only safe counts/identifiers."""
    return verify_archive(directory, master_key).summary()


@_safe
def restore_synthetic(directory, master_key, destination):
    """TEST ONLY: opaque files + key/metadata mapping in a NEW system-temp child.

    Never interpret object keys as local paths. No replacement, rollback or cleanup.
    Validate all encrypted artifacts before creating a plaintext test destination.
    """
    archive = verify_archive(directory, master_key)
    require(archive.core['scope'] == 'synthetic-local', 'S3_SYNTHETIC_ONLY')
    destination = Path(destination).absolute()
    require('..' not in destination.parts, 'S3_PATH_TRAVERSAL')
    _no_links(destination)
    root = Path(tempfile.gettempdir()).resolve()
    require(root in destination.resolve().parents, 'S3_RESTORE_REQUIRES_SYSTEM_TEMP')
    require(not destination.exists(), 'S3_DESTINATION_EXISTS')
    require(archive.directory.resolve() not in destination.resolve().parents, 'S3_RESTORE_INSIDE_ARCHIVE')
    _directory(destination.parent)
    destination.mkdir(mode=0o700)
    private_directory(destination)
    # Windows mkdir/private_directory may retain explicit non-user grants.
    # Initialize/audit ONLY this newly created empty synthetic destination.
    from src.recovery.s3_safety import session_permissions
    session_permissions(destination, initialize=True)
    mapping = []
    for item in archive.index['objects']:
        name = f"object-{item['object_id']:08d}.bin"
        # Generated numeric name; never derived from item['key'].
        path = destination / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
            for plain in archive._chunks(item):
                output.write(plain)
        checksum = hashlib.sha256()
        with path.open('rb') as restored:
            while True:
                block = restored.read(archive.core['chunk_size'])
                if not block:
                    break
                checksum.update(block)
        require(path.stat().st_size == item['size_bytes'] and checksum.hexdigest() == item['sha256'], 'S3_RESTORE_CHECKSUM')
        mapping.append({**{k: item[k] for k in ('key', 'metadata', 'size_bytes', 'sha256')}, 'file': name})
    exclusive_write(destination / 'index.json', encoded({'scope': 'SYNTHETIC_LOCAL_ONLY', 'objects': mapping}))
    return archive.summary()
