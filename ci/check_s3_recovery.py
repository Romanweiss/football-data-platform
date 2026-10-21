"""Explicit synthetic-only S3/profile-v1 gate, shared by Linux and Windows CI.

No operator command, production environment file, Docker service or real archive
is opened. Tests own ephemeral fake payloads/keys. Outbound socket creation fails.
"""
from pathlib import Path
import importlib.util
import ssl  # Initialize the real socket subclass before the network guard.
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci.run_unittest import install_compatibility


def main():
    missing = [name for name in ('cryptography', 'boto3') if importlib.util.find_spec(name) is None]
    if missing:
        print('Synthetic recovery dependencies missing: ' + ', '.join(missing), file=sys.stderr)
        return 2
    install_compatibility()
    root = Path(__file__).resolve().parents[1]
    with patch('socket.socket', side_effect=AssertionError('S3_CI_NETWORK_FORBIDDEN')), \
         patch('socket.create_connection', side_effect=AssertionError('S3_CI_NETWORK_FORBIDDEN')):
        loader = unittest.TestLoader()
        suite = unittest.TestSuite([
            loader.discover(str(root / 'tests'), pattern='test_s3_*.py'),
            loader.discover(str(root / 'tests'), pattern='test_recovery.py'),
        ])
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
