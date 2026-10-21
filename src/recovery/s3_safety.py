"""Operator path, permission, space and key gates. No cloud or database writes."""
import base64
import json
import os
from pathlib import Path
import shutil
import stat

from src.recovery.archive import exclusive_write, private_directory
from src.recovery.runtime import docker, require, run
from src.recovery.s3_archive import MAX_CHUNK, MAX_CHUNKS, MAX_INDEX, MAX_OBJECTS, OVERHEAD, _no_links
from src.recovery.s3_workflow import MAX_EVIDENCE, guarded

WORKSPACE = Path(__file__).resolve().parents[2]
SECRET_PARTS = {'.git', '.venv', '.recovery-keys', '.env', '.passes', 'keys.txt',
                'secrets', 'docker-desktop-data', 'docker-desktop'}
DOCKER_ROOTS = (Path('/var/lib/docker'), Path('/var/lib/containers'), Path('/run/desktop'))


def _within(path, parent):
    return path == parent or parent in path.parents


@guarded
def safe_path(value, *, workspace=WORKSPACE, forbidden_roots=()):
    require(value is not None, 'S3_EXPLICIT_PATH_REQUIRED')
    raw = str(value)
    require(not raw.startswith(('\\\\', '//')) and '\x00' not in raw, 'S3_UNSAFE_OUTPUT_PATH')
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'S3_ABSOLUTE_NONTRAVERSING_PATH_REQUIRED')
    require(path != Path(path.anchor) and not any(p.casefold() in SECRET_PARTS for p in path.parts),
            'S3_SECRET_OR_ROOT_PATH_REFUSED')
    _no_links(path)
    path, workspace = path.resolve(), Path(workspace).resolve()
    require(not _within(path, workspace) and not _within(workspace, path), 'S3_WORKSPACE_PATH_REFUSED')
    require(not any((parent / '.git').exists() for parent in (path, *path.parents)),
            'S3_GIT_WORKSPACE_PATH_REFUSED')
    for root in (*DOCKER_ROOTS, *forbidden_roots):
        root = Path(root)
        if root.is_absolute():
            require(not _within(path, root.resolve()), 'S3_DOCKER_VOLUME_PATH_REFUSED')
    if os.name == 'nt':
        for name in ('PROGRAMDATA', 'LOCALAPPDATA'):
            if os.environ.get(name):
                for directory in ('Docker', 'DockerDesktop'):
                    require(not _within(path, (Path(os.environ[name]) / directory).resolve()),
                            'S3_DOCKER_VOLUME_PATH_REFUSED')
    return path


@guarded
def docker_volume_roots():
    """Read mountpoints only, never container environments or volume contents."""
    names = docker('volume', 'ls', '-q').decode().split()
    roots = []
    for name in names:
        mount = docker('volume', 'inspect', '--format', '{{.Mountpoint}}', name).decode().strip()
        require(bool(mount), 'S3_DOCKER_VOLUME_IDENTITY_UNKNOWN')
        roots.append(Path(mount))
    return tuple(roots)


def _powershell(script):
    command = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', command])


@guarded
def session_permissions(path, *, initialize=False):
    """Set an exact ACL ONLY on a newly created empty directory, otherwise audit."""
    path = Path(path)
    if initialize:
        _no_links(path)
        require(path.is_dir() and not any(path.iterdir()), 'S3_NEW_EMPTY_PRIVATE_DIRECTORY_REQUIRED')
        if os.name == 'nt':
            literal = str(path).replace("'", "''")
            _powershell("$ErrorActionPreference='Stop'; $p='" + literal + "'; " + r'''
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=Get-Acl -LiteralPath $p
$others=@($acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) |
  Where-Object {$_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -ne $sid.Value} |
  ForEach-Object {$_.IdentityReference.Value} | Sort-Object -Unique)
foreach($id in $others) {
  & icacls $p /remove:g ('*'+$id) | Out-Null
  if($LASTEXITCODE -ne 0){throw 'ACL_SETUP_FAILED'}
}
''')
        else:
            private_directory(path)
    assert_private(path, children=True)


@guarded
def assert_private(path, *, children=False):
    """Read-only audit; never silently chmod an existing operator directory/key."""
    path = Path(path)
    _no_links(path)
    require(path.exists(), 'S3_PRIVATE_PATH_MISSING')
    items = [path, *path.iterdir()] if children and path.is_dir() else [path]
    for item in items:
        _no_links(item)
        require(item.is_dir() or (item.is_file() and item.stat().st_nlink == 1), 'S3_UNSAFE_PRIVATE_FILE')
    if os.name == 'nt':
        # Literal path is escaped as a PS single-quoted string; no CLI secret material.
        literal = str(path).replace("'", "''")
        script = "$ErrorActionPreference='Stop'; $p='" + literal + "'; " + r'''
$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$items=@(Get-Item -LiteralPath $p -Force)
'''
        if children:
            script += "$items+=@(Get-ChildItem -LiteralPath $p -Force);\n"
        script += r'''
$ok=$true
foreach($item in $items) {
  $acl=Get-Acl -LiteralPath $item.FullName
  if($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid.Value){$ok=$false}
  if($item.PSIsContainer -and -not $acl.AreAccessRulesProtected){$ok=$false}
  $allowed=0
  foreach($rule in $acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])) {
    if($rule.AccessControlType -eq 'Allow') {
      if($rule.IdentityReference.Value -ne $sid.Value){$ok=$false} else {$allowed+=1}
    }
  }
  if($allowed -eq 0){$ok=$false}
}
@{safe=$ok}|ConvertTo-Json -Compress
'''
        result = json.loads(_powershell(script))
        require(result.get('safe') is True, 'S3_UNSAFE_PERMISSIONS')
    else:
        for item in items:
            info = item.stat()
            require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                    'S3_UNSAFE_PERMISSIONS')


@guarded
def prepare_directory(value, *, confirmed=False, forbidden_roots=()):
    require(confirmed is True, 'S3_DIRECTORY_CREATION_CONFIRMATION_REQUIRED')
    path = safe_path(value, forbidden_roots=forbidden_roots)
    require(path.parent.is_dir() and not path.exists(), 'S3_NEW_DIRECTORY_REQUIRED')
    path.mkdir(mode=0o700)  # No parents, reuse, removal or cleanup on failure.
    private_directory(path)
    session_permissions(path, initialize=True)
    return {'status': 'PRIVATE_DIRECTORY_CREATED', 'independent_storage_verified': False}


@guarded
def locations(destination, key_file, *, forbidden_roots=()):
    destination = safe_path(destination, forbidden_roots=forbidden_roots)
    key_file = safe_path(key_file, forbidden_roots=forbidden_roots)
    require(destination.is_dir() and key_file.parent.is_dir(), 'S3_DESTINATION_OR_KEY_DIRECTORY_MISSING')
    require(not _within(key_file.parent, destination) and not _within(destination, key_file.parent),
            'S3_KEY_MUST_BE_SEPARATE')
    assert_private(destination)
    assert_private(key_file.parent)
    return destination, key_file


@guarded
def load_key(key_file):
    key_file = Path(key_file)
    _no_links(key_file)
    assert_private(key_file.parent)
    assert_private(key_file)
    require(key_file.is_file() and key_file.stat().st_size == 32, 'S3_INVALID_KEY_FILE')
    with key_file.open('rb') as stream:
        key = stream.read(33)
    require(len(key) == 32, 'S3_INVALID_KEY_FILE')
    return key


@guarded
def generate_key(key_file, *, confirmed=False, forbidden_roots=()):
    require(confirmed is True, 'S3_KEY_GENERATION_CONFIRMATION_REQUIRED')
    path = safe_path(key_file, forbidden_roots=forbidden_roots)
    require(path.parent.is_dir() and not path.exists(), 'S3_NEW_KEY_FILE_REQUIRED')
    assert_private(path.parent)
    exclusive_write(path, os.urandom(32))
    # Files inherit only their already-private parent ACL. Audit, do not grant on failure.
    assert_private(path)
    with path.open('r+b') as stream:
        os.fsync(stream.fileno())
        require(len(stream.read(33)) == 32, 'S3_INVALID_KEY_FILE')
    return {'status': 'KEY_CREATED', 'key_recovery_verified': False}


def space_plan(total_bytes, object_count, *, chunk_size=MAX_CHUNK):
    require(type(total_bytes) is int and total_bytes >= 0 and type(object_count) is int
            and 0 <= object_count < MAX_OBJECTS and 1 <= chunk_size <= MAX_CHUNK, 'S3_INVALID_SPACE_INPUT')
    chunks = (total_bytes + chunk_size - 1) // chunk_size + object_count + (MAX_EVIDENCE + chunk_size - 1) // chunk_size
    require(chunks <= MAX_CHUNKS, 'S3_TOO_MANY_CHUNKS')
    # Upper bound includes the encrypted evidence object, max index, per-chunk overhead and headers.
    upper = total_bytes + MAX_EVIDENCE + MAX_INDEX + chunks * OVERHEAD + 131072
    reserve = max(64 * 1024 * 1024, (upper + 3) // 4)
    return {'source_bytes': total_bytes, 'source_objects': object_count,
            'archive_upper_bound_bytes': upper, 'reserve_bytes': reserve,
            'required_free_bytes': upper + reserve, 'independent_storage_verified': False}


@guarded
def check_space(destination, plan, *, sealing=False):
    free = shutil.disk_usage(destination).free
    required = plan['reserve_bytes'] if sealing else plan['required_free_bytes']
    require(free >= required, 'S3_INSUFFICIENT_FREE_SPACE')
    return {'free_bytes': free, 'required_free_bytes': required}
