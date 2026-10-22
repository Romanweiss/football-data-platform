"""Allowlisted diagnostics only; never format exception messages or provider text."""
import ssl

from src.recovery.runtime import RecoveryError

OPERATIONS = frozenset(('list_objects_v2', 'head_object', 'get_object', 'read_body',
                        'get_bucket_versioning', 'get_object_lock_configuration',
                        'list_object_versions', 'reconcile_metadata', 'unknown'))
CATEGORIES = frozenset(('TLS_FAILURE', 'TIMEOUT', 'CREDENTIAL_FAILURE', 'ACCESS_DENIED',
                        'OBJECT_NOT_FOUND', 'PRECONDITION_FAILED', 'TRANSPORT_FAILURE',
                        'METADATA_INCONSISTENCY', 'SOURCE_CHANGED', 'UNKNOWN'))
READ_CODES = frozenset(('S3_READ_TLS_FAILED', 'S3_READ_TIMEOUT', 'S3_READ_CREDENTIALS_FAILED',
                       'S3_READ_HTTP_403', 'S3_READ_HTTP_404', 'S3_READ_HTTP_412',
                       'S3_READ_HTTP_FAILED', 'S3_STREAM_READ_FAILED'))
METADATA_CODES = frozenset('''
S3_ARCHIVE_SOURCE_KEY_SET S3_BRONZE_BYTES_MISMATCH S3_BRONZE_METADATA_SHA
S3_BRONZE_PARENT_IDENTITY S3_BRONZE_PARENT_MISSING S3_BRONZE_VERSIONED_KEY
S3_BUILD_CONTEXT_OR_COUNTS S3_BUILD_EXACT_FILE_SET S3_BUILD_PREFIX S3_CATALOG_BUCKET
S3_CATALOG_SCHEMA S3_CATALOG_SIZE S3_CONTEXT_MATCH_MEMBERSHIP S3_DETERMINISTIC_BUILD_ID
S3_DIRECTORY_MARKER_SIZE S3_DOCUMENT_SIZE S3_DUPLICATE_BRONZE_RECORD S3_DUPLICATE_BUILD
S3_DUPLICATE_BUILD_LOCATION S3_DUPLICATE_LOAD_RECEIPT S3_DUPLICATE_MANIFEST_FILE
S3_GOLD_INPUT_DATASETS S3_GOLD_INPUT_FINGERPRINT S3_INVALID_PARQUET_PART S3_LOAD_DATABASE
S3_LOAD_TARGET_IDENTITY S3_MANIFEST_CATALOG_IDENTITY S3_MANIFEST_FILE_COUNT
S3_MANIFEST_METADATA S3_MANIFEST_MISSING S3_MANIFEST_PART_METADATA S3_MATCHES_PARENT_COUNT
S3_METADATA_SNAPSHOT_SCHEMA S3_REGISTERED_OBJECT_MISSING S3_SILVER_INPUT_FINGERPRINT
S3_SILVER_PARENT_IDENTITY S3_SILVER_PARENT_MISSING S3_UNEXPECTED_DOCUMENT
S3_METADATA_BASELINE_CHANGED
'''.split())


class S3ReadError(RecoveryError):
    """Preserve legacy str(error) for existing 403/404/412 control flow."""
    def __init__(self, code, category, operation):
        super().__init__(code)
        self.category, self.operation = category, operation


def read_error(exc, operation, *, stream=False):
    category, code = 'TRANSPORT_FAILURE', 'S3_READ_HTTP_FAILED'
    if isinstance(exc, ssl.SSLError):
        category, code = 'TLS_FAILURE', 'S3_READ_TLS_FAILED'
    elif isinstance(exc, TimeoutError):
        category, code = 'TIMEOUT', 'S3_READ_TIMEOUT'
    # Optional SDK import: pure repository/synthetic callers do not need boto3.
    try:
        from botocore import exceptions as sdk
    except ImportError:
        sdk = None
    if sdk is not None:
        if isinstance(exc, sdk.SSLError):
            category, code = 'TLS_FAILURE', 'S3_READ_TLS_FAILED'
        elif isinstance(exc, (sdk.ConnectTimeoutError, sdk.ReadTimeoutError)):
            category, code = 'TIMEOUT', 'S3_READ_TIMEOUT'
        elif isinstance(exc, (sdk.NoCredentialsError, sdk.PartialCredentialsError, sdk.CredentialRetrievalError)):
            category, code = 'CREDENTIAL_FAILURE', 'S3_READ_CREDENTIALS_FAILED'
    response = getattr(exc, 'response', None)
    if isinstance(response, dict):
        metadata, error = response.get('ResponseMetadata'), response.get('Error')
        status = metadata.get('HTTPStatusCode') if isinstance(metadata, dict) else None
        provider_code = error.get('Code') if isinstance(error, dict) else None
        if type(status) is int and status in (403, 404, 412):
            code = 'S3_READ_HTTP_' + str(status)
            category = {403: 'ACCESS_DENIED', 404: 'OBJECT_NOT_FOUND', 412: 'PRECONDITION_FAILED'}[status]
        if isinstance(provider_code, str) and provider_code in (
                'InvalidAccessKeyId', 'SignatureDoesNotMatch', 'InvalidToken', 'ExpiredToken',
                'TokenRefreshRequired', 'UnrecognizedClientException'):
            category = 'CREDENTIAL_FAILURE'
            if status != 403:
                code = 'S3_READ_CREDENTIALS_FAILED'
    return S3ReadError('S3_STREAM_READ_FAILED' if stream else code, category,
                       operation if operation in OPERATIONS else 'unknown')


def _diagnostic(exc):
    """Only exact known codes/enum values; not arbitrary RecoveryError messages."""
    result = {'code': 'S3_HOST_READINESS_FAILED', 'category': 'UNKNOWN', 'operation': 'unknown'}
    if isinstance(exc, S3ReadError):
        code = str(exc)
        if code in READ_CODES and exc.category in CATEGORIES and exc.operation in OPERATIONS:
            return {'code': code, 'category': exc.category, 'operation': exc.operation}
    elif isinstance(exc, RecoveryError):
        code = str(exc)
        if code in METADATA_CODES:
            return {'code': code, 'category': 'METADATA_INCONSISTENCY', 'operation': 'reconcile_metadata'}
        if code == 'S3_SOURCE_CHANGED':
            return {'code': code, 'category': 'SOURCE_CHANGED', 'operation': 'unknown'}
        if code in ('S3_HOST_CA_INVALID', 'S3_HOST_CA_R6_MISSING', 'S3_HOST_TLS_REQUIRED',
                    'S3_OPERATOR_CA_BUNDLE_MISSING'):
            return {'code': code, 'category': 'TLS_FAILURE', 'operation': 'unknown'}
    # SDK construction can fail before the read adapter exists; classify by type only.
    elif isinstance(exc, Exception):
        classified = read_error(exc, 'unknown')
        if classified.category in ('TLS_FAILURE', 'TIMEOUT', 'CREDENTIAL_FAILURE'):
            return {'code': str(classified), 'category': classified.category, 'operation': 'unknown'}
    return result


def safe_diagnostic(exc):
    """Malformed exception attributes also fail closed, without a secondary traceback."""
    try:
        return _diagnostic(exc)
    except Exception:
        return {'code': 'S3_HOST_READINESS_FAILED', 'category': 'UNKNOWN', 'operation': 'unknown'}
