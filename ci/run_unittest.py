"""Run stdlib unittest with its enterContext cleanup API on Python 3.10 too."""
from pathlib import Path
import sys
import unittest


def enter_context(test_case, context):
    """Match TestCase.enterContext: register __exit__ as an unconditional cleanup."""
    context_type = type(context)
    try:
        enter = context_type.__enter__
        exit_context = context_type.__exit__
    except AttributeError:
        raise TypeError('Object does not support the context manager protocol') from None
    result = enter(context)
    test_case.addCleanup(exit_context, context, None, None, None)
    return result


def install_compatibility():
    if not hasattr(unittest.TestCase, 'enterContext'):
        unittest.TestCase.enterContext = enter_context


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    install_compatibility()
    unittest.main(module=None)
