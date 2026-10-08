"""Private stdio JSON bridge; invokes existing CLIs, never emits their raw logs."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.orchestration.runtime import execute
from src.dq.orchestration import DQGateError
from src.alerts.operations import observe_operation
from src.alerts.transport import LOG_SINK, DELIVERY_BUDGET


if __name__ == "__main__":
    request = {}
    notifications = []
    LOG_SINK.set(notifications.append)
    DELIVERY_BUDGET.set(10)  # Whole bridge budget, not ten per DQ suite/observer.
    try:
        request = json.load(sys.stdin)
        result = execute(request)
        if request['step'] != 'source_discovery' and result.get('status') != 'BUSY':
            result['operational_alerts'] = observe_operation(request,passed=True)
        if notifications:
            result['notifications'] = notifications[:10]
        print(json.dumps(result))
    except DQGateError as exc:
        observe_operation(request,passed=False,dq_reported=exc.summary.get('dq_persisted',False))
        print(json.dumps({'exception':'DQGateError', 'message':'Persistent DQ gate failed', **exc.summary,
                          'notifications':notifications[:10]}))
        sys.exit(1)
    except Exception as exc:
        # RuntimeError from our allowlisted run_cli has a safe fixed-format message.
        message = str(exc) if type(exc) is RuntimeError and str(exc).startswith("CLI failed: script=") else "Project adapter failed"
        from src.common.http import DownloadError
        from src.common.source_transport import SourceAccessError
        source_access = isinstance(exc,(SourceAccessError,DownloadError)) or (isinstance(exc, RuntimeError) and any('exception=' + name in str(exc) for name in ('SourceAccessError','DownloadError')))
        if not getattr(exc,'operation_alert_handled',False) and not request.get('dry_run'):
            observe_operation(request,passed=False,source_access=source_access)
        print(json.dumps({"exception": type(exc).__name__, "message": message,'notifications':notifications[:10]}))
        sys.exit(1)
