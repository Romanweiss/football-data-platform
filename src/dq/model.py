"""Small, secret-safe rule execution contract. No IO at import time."""
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from uuid import uuid4

from src.orchestration.commands import context, digest

CATEGORIES = frozenset(('source_integrity', 'structural', 'referential', 'semantic',
                        'reconciliation', 'regression', 'operational'))
STATUSES = ('PASS', 'FAIL', 'WARN', 'SKIP')


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    layer: str
    dataset: str
    description: str
    severity: str = 'ERROR'

    def __post_init__(self):
        if (not re.fullmatch(r'[a-z][a-z0-9_.]{2,159}', self.rule_id)
                or self.category not in CATEGORIES or self.severity not in ('ERROR', 'WARNING', 'INFO')
                or self.layer not in ('bronze', 'silver', 'gold', 'serving', 'api', 'operational')
                or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.dataset)
                or not 1 <= len(self.description) <= 240):
            raise ValueError('Invalid DQ rule definition')


class Discard:
    """Do not buffer/parse/forward arbitrary legacy validator or driver output."""
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def scalar(value):
    # Metrics only; never URLs, object keys, exception strings or dataset payloads.
    if value is None or type(value) is bool:
        return value
    if type(value) is int and abs(value) <= 10**30:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError('DQ observations must be bounded finite numeric scalars')


def state(results):
    statuses = {r['status'] for r in results}
    return ('FAIL' if 'FAIL' in statuses else 'WARN' if 'WARN' in statuses else
            'PASS' if 'PASS' in statuses else 'SKIP')


class Run:
    def __init__(self, ctx, suite, *, airflow=None):
        self.context = context(ctx)
        if not re.fullmatch(r'[a-z][a-z0-9_.]{0,119}', suite):
            raise ValueError('Invalid DQ suite')
        self.suite = suite
        self.execution_id = str(uuid4())
        self.started_at = now()
        self.results = []
        self.airflow = dict(airflow or {})
        if self.airflow and (set(self.airflow) != {'dag_id', 'run_id', 'task_id'} or any(
                not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_.:+-]{1,250}', v)
                for v in self.airflow.values())):
            raise ValueError('Invalid Airflow linkage')

    def record(self, rule, *, passed=True, observed=None, expected=None, build_id=None,
               skip=False, reason='evaluated'):
        if reason not in ('evaluated', 'prerequisite failed', 'not applicable', 'validator failed', 'runtime failed'):
            raise ValueError('Unrecognized safe DQ reason')
        if any(r['rule_id'] == rule.rule_id for r in self.results):
            raise ValueError('Duplicate rule in one execution')
        if len(self.results) >= 1000:
            raise ValueError('DQ result budget exceeded')
        status = ('SKIP' if skip else 'PASS' if passed else
                  'WARN' if rule.severity in ('WARNING', 'INFO') else 'FAIL')
        result = dict(rule_id=rule.rule_id, timestamp=now(), **self.context,
                      category=rule.category, layer=rule.layer, dataset=rule.dataset,
                      build_id=digest(build_id) if build_id is not None else None,
                      status=status, severity=rule.severity, observed=scalar(observed),
                      expected=scalar(expected), message=rule.description + '; ' + reason)
        self.results.append(result)
        return result

    def call(self, rule, function, *, build_id=None):
        try:
            with redirect_stdout(Discard()), redirect_stderr(Discard()):
                value = function()
        except Exception as error:
            # Even project exceptions may contain paths or externally supplied text.
            integrity = isinstance(error, (ValueError, AssertionError)) or any(
                name in type(error).__name__ for name in ('IntegrityError', 'QualityError', 'ConflictError'))
            if integrity or rule.category == 'operational':
                self.record(rule, passed=False, build_id=build_id, reason='validator failed' if integrity else 'runtime failed')
            else:
                self.record(rule, skip=True, build_id=build_id, reason='prerequisite failed')
                self.record(Rule('operational.' + rule.rule_id, 'operational', rule.layer, rule.dataset,
                                 'Validator dependency execution failed'), passed=False,
                            build_id=build_id, reason='runtime failed')
            return False, None
        self.record(rule, build_id=build_id)
        return True, value

    def report(self):
        counts = Counter(r['status'] for r in self.results)
        return dict(contract_version=1, execution_id=self.execution_id, **self.context,
                    suite=self.suite, started_at=self.started_at, finished_at=now(),
                    status=state(self.results), counts={s: counts[s] for s in STATUSES},
                    layers={layer: state([r for r in self.results if r['layer'] == layer])
                            for layer in sorted({r['layer'] for r in self.results})},
                    airflow=self.airflow, results=list(self.results))
