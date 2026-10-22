"""Bounded, read-only SDK transport. No destination adapter or cloud write API."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

from src.recovery.runtime import RecoveryError, digest, encoded, require
from src.recovery.s3_archive import _metadata
from src.recovery.s3_diagnostics import read_error
from src.recovery.s3_storage import Head, ListEntry, Page, ReadResult, StorageIdentity
from src.recovery.s3_workflow import guarded


def canonical_identity(endpoint, bucket):
    parsed = urlsplit(endpoint)
    require(parsed.scheme.lower() == 'https' and parsed.hostname and not parsed.username
            and not parsed.password and parsed.path in ('', '/') and not parsed.query
            and not parsed.fragment, 'S3_UNSAFE_ENDPOINT')
    require(isinstance(bucket, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket)
            is not None, 'S3_INVALID_BUCKET')
    port = '' if parsed.port in (None, 443) else ':' + str(parsed.port)
    host = parsed.hostname.lower() + port
    endpoint = 'https://' + host
    path_alias = endpoint + '/' + bucket
    virtual_alias = 'https://' + bucket + '.' + host
    # Endpoint-bound identity, NOT proof of global bucket ownership across providers.
    return StorageIdentity(endpoint, bucket, 'endpoint-bucket:' + digest(encoded([endpoint, bucket])),
                           (path_alias, virtual_alias), 'live-read-only')


def _date(value):
    require(isinstance(value, datetime) and value.tzinfo is not None, 'S3_INVALID_TIMESTAMP')
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _etag(value):
    require(isinstance(value, str) and bool(value) and '\r' not in value and '\n' not in value, 'S3_INVALID_ETAG')
    return value  # Exact native value, including quotes/multipart suffix; not a checksum.


def _status(response, expected):
    require(isinstance(response, dict)
            and response.get('ResponseMetadata', {}).get('HTTPStatusCode') == expected, 'S3_INVALID_HTTP_RESPONSE')


def _head(response, *, size=None):
    length = response['ContentLength'] if size is None else size
    require(type(length) is int and length >= 0, 'S3_INVALID_CONTENT_LENGTH')
    meta = response.get('Metadata', {})
    require(isinstance(meta, dict) and all(isinstance(k, str) and isinstance(v, str)
            and not k.startswith('s3:') for k, v in meta.items()), 'S3_INVALID_USER_METADATA')
    meta = dict(meta)
    for field in ('ContentType', 'ContentEncoding', 'ContentDisposition', 'ContentLanguage',
                  'CacheControl', 'Expires', 'WebsiteRedirectLocation', 'VersionId',
                  'StorageClass', 'ServerSideEncryption', 'SSEKMSKeyId', 'BucketKeyEnabled'):
        if field in response:
            value = response[field]
            require(isinstance(value, (str, bool, datetime)), 'S3_INVALID_HEADER')
            meta['s3:' + field] = _date(value) if isinstance(value, datetime) else str(value)
    _metadata(meta)  # Same flat-string/index-size rules as schema 2; no encryption/key creation.
    return Head(length, _date(response['LastModified']), _etag(response['ETag']), meta)


@dataclass
class ReadBudget:
    max_object_bytes: int = 256 * 1024
    max_total_bytes: int = 2 * 1024 * 1024
    consumed_bytes: int = 0

    def reserve(self, length):
        require(type(length) is int and 0 <= length <= self.max_object_bytes
                and self.consumed_bytes + length <= self.max_total_bytes, 'S3_DRY_RUN_BYTE_LIMIT')


class FullReadBudget(ReadBudget):
    """Only explicitly authorized workflow inventory can expand the dry-run quota."""

    def reserve(self, length):
        require(type(length) is int and 0 <= length <= self.max_object_bytes
                and self.consumed_bytes + length <= self.max_total_bytes, 'S3_FULL_READ_BYTE_LIMIT')


class _BoundedBody:
    def __init__(self, raw, length, budget):
        self.raw, self.length, self.budget = raw, length, budget
        self.read_bytes, self.closed = 0, False

    def read(self, size):
        try:
            require(not self.closed and type(size) is int and 0 < size <= 65536, 'S3_UNBOUNDED_READ')
            remaining = self.length - self.read_bytes
            if remaining == 0:
                return b''
            self.budget.reserve(min(size, remaining))
            block = self.raw.read(min(size, remaining))
            require(isinstance(block, bytes) and 0 < len(block) <= min(size, remaining), 'S3_STREAM_TRUNCATED')
            self.read_bytes += len(block)
            self.budget.consumed_bytes += len(block)
            return block
        except RecoveryError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise read_error(exc, 'read_body', stream=True) from None

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.raw.close()
            except Exception:
                raise RecoveryError('S3_STREAM_CLOSE_FAILED') from None


class S3ReadOnly:
    """Injected boto3 client; every GET requires a native HEAD IfMatch validator.

    Advertised capabilities describe adapter operations, not proof of server rights.
    Production credential material remains owned by the existing SDK runtime.
    """
    @guarded
    def __init__(self, client, bucket, *, budget=None):
        self._client = client
        self.identity = canonical_identity(client.meta.endpoint_url, bucket)
        require(client.meta.config.s3.get('addressing_style') == 'virtual'
                and client.meta.config.signature_version == 's3v4', 'S3_CLIENT_CONFIG')
        self.budget = budget or ReadBudget()
        require(type(self.budget) is ReadBudget, 'S3_DRY_RUN_BUDGET_REQUIRED')
        require(type(self.budget.max_object_bytes) is int and 0 < self.budget.max_object_bytes <= 1024 * 1024
                and type(self.budget.max_total_bytes) is int and 0 < self.budget.max_total_bytes <= 8 * 1024 * 1024
                and self.budget.consumed_bytes == 0, 'S3_INVALID_DRY_RUN_BUDGET')
        self.calls = {'list': 0, 'head': 0, 'get': 0}
        self._owner_reference = None

    def capabilities(self):
        return frozenset(('list', 'head', 'get', 'conditional_get'))

    @guarded
    def authorize_full_read(self, initial, *, confirmed=False):
        require(confirmed is True and type(self.budget) is ReadBudget, 'S3_FULL_READ_CONFIRMATION_REQUIRED')
        sizes = [v['head']['size_bytes'] for v in initial.values()]
        require(all(type(n) is int and n >= 0 for n in sizes), 'S3_INVALID_OBJECT_SIZE')
        self.budget = FullReadBudget(max(1, max(sizes, default=0)),
                                    self.budget.consumed_bytes + sum(sizes), self.budget.consumed_bytes)

    def _call(self, operation, **kwargs):
        try:
            return getattr(self._client, operation)(Bucket=self.identity.bucket, **kwargs)
        except Exception as exc:
            raise read_error(exc, operation) from None

    @guarded
    def list_page(self, token=None):
        require(token is None or isinstance(token, str) and bool(token), 'S3_INVALID_PAGE_TOKEN')
        args = {} if token is None else {'ContinuationToken': token}
        self.calls['list'] += 1
        response = self._call('list_objects_v2', MaxKeys=1000, **args)
        _status(response, 200)
        objects = []
        for row in response.get('Contents', []):
            require(isinstance(row['Key'], str) and bool(row['Key'])
                    and type(row['Size']) is int and row['Size'] >= 0, 'S3_INVALID_LIST_OBJECT')
            objects.append(ListEntry(row['Key'], row['Size'], _date(row['LastModified']), _etag(row['ETag'])))
        require(type(response['KeyCount']) is int and response['KeyCount'] == len(objects)
                and type(response['IsTruncated']) is bool, 'S3_INVALID_LIST_PAGE')
        truncated, next_token = response['IsTruncated'], response.get('NextContinuationToken')
        require((truncated and isinstance(next_token, str) and bool(next_token) and bool(objects))
                or (not truncated and next_token is None), 'S3_INCOMPLETE_PAGINATION')
        return Page(tuple(objects), len(objects), truncated, next_token)

    @guarded
    def head_object(self, key):
        self.calls['head'] += 1
        response = self._call('head_object', Key=key)
        _status(response, 200)
        return _head(response)

    @guarded
    def _get(self, key, expected, *, sample=False, validator=None):
        require(isinstance(expected, Head), 'S3_EXPECTED_HEAD_REQUIRED')
        length = min(1, expected.size_bytes) if sample else expected.size_bytes
        self.budget.reserve(length)  # Reject oversized full GET before issuing a request.
        args = {'Key': key, 'IfMatch': expected.etag if validator is None else _etag(validator)}
        ranged = sample and expected.size_bytes > 0
        if ranged:
            args['Range'] = 'bytes=0-0'
        self.calls['get'] += 1
        response = self._call('get_object', **args)
        body = response.get('Body')
        try:
            _status(response, 206 if ranged else 200)
            require(response['ContentLength'] == length, 'S3_GET_LENGTH_MISMATCH')
            if ranged:
                require(response.get('ContentRange') == f'bytes 0-0/{expected.size_bytes}', 'S3_INVALID_CONTENT_RANGE')
            actual = _head(response, size=expected.size_bytes)
            require(actual == expected, 'S3_GET_HEAD_STATE_CHANGED')
            require(body is not None and callable(body.read) and callable(body.close), 'S3_INVALID_STREAM')
            return ReadResult(actual, _BoundedBody(body, length, self.budget))
        except Exception:
            if body is not None:
                body.close()
            raise

    def get_object(self, key, *, expected):
        return self._get(key, expected)

    def sample_object(self, key, *, expected):
        return self._get(key, expected, sample=True)

    @guarded
    def conditional_probe(self, key, *, expected):
        with self.sample_object(key, expected=expected) as result:
            result.body.read(1)
        # IfMatch is a comma-separated ETag list: ensure the deliberate validator differs.
        invalid = '"' + ('0' if expected.etag != '"' + '0' * 64 + '"' else '1') * 64 + '"'
        try:
            with self._get(key, expected, sample=True, validator=invalid):
                pass
        except RecoveryError as exc:
            if str(exc) == 'S3_READ_HTTP_412':
                return {'correct_validator': 'PASS', 'incorrect_validator': 'HTTP_412', 'status': 'PASS'}
            raise
        raise RecoveryError('S3_CONDITIONAL_GET_NOT_ENFORCED')

    @guarded
    def optional_capabilities(self):
        result = {}
        for label, operation, args in (
            ('versioning', 'get_bucket_versioning', {}),
            ('object_lock', 'get_object_lock_configuration', {}),
            ('list_versions', 'list_object_versions', {'MaxKeys': 1}),
        ):
            try:
                response = self._call(operation, **args)
                _status(response, 200)
                result[label] = {'access': 'ALLOWED', 'status': response.get('Status', 'UNSPECIFIED')
                                 if label == 'versioning' else 'OBSERVABLE_NOT_BACKED_UP'}
            except RecoveryError as exc:
                require(str(exc) in ('S3_READ_HTTP_403', 'S3_READ_HTTP_404'), 'S3_CAPABILITY_PROBE_FAILED')
                result[label] = {'access': str(exc).removeprefix('S3_READ_'), 'state': 'UNKNOWN'}
        return result

    def describe_identity(self):
        return {**asdict(self.identity), 'addressing': 'virtual', 'account_project_reference': self._owner_reference,
                'ownership_resolution': 'ENDPOINT_BOUND_ONLY', 'live_restore_enabled': False}

    @guarded
    def owner_reference(self):
        """A non-secret fingerprint if LIST exposes S3 canonical owner, not project ID.

        This does not resolve unknown destination aliases or enable any restore.
        """
        try:
            self.calls['list'] += 1
            response = self._call('list_objects_v2', MaxKeys=1, FetchOwner=True)
        except RecoveryError as exc:
            require(str(exc) == 'S3_READ_HTTP_403', 'S3_OWNER_PROBE_FAILED')
            return {'access': 'HTTP_403', 'state': 'UNKNOWN'}
        _status(response, 200)
        owners = {r.get('Owner', {}).get('ID') for r in response.get('Contents', [])}
        require(all(value is None or isinstance(value, str) for value in owners), 'S3_INVALID_OWNER_RESPONSE')
        owners.discard(None)
        require(len(owners) <= 1, 'S3_OWNER_AMBIGUOUS')
        if owners:
            self._owner_reference = 's3-canonical-owner-sha256:' + digest(next(iter(owners)).encode())
        return {'access': 'ALLOWED', 'state': 'CANONICAL_OWNER_FINGERPRINT' if owners else 'NOT_EXPOSED'}
