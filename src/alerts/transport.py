"""Small transport contract; only the explicit local/log provider is shipped."""
import json
import time
import sys
from contextvars import ContextVar
from typing import Protocol


class TransientDeliveryError(Exception):
    pass


class PermanentDeliveryError(Exception):
    pass


class InvalidProviderConfiguration(Exception):
    pass


class Transport(Protocol):
    def send(self, notification: dict) -> None: ...


class LogTransport:
    def send(self, notification):
        sink = LOG_SINK.get()
        if sink is not None:
            sink(notification)
        else:
            print('Platform notification: ' + json.dumps(notification,sort_keys=True), file=sys.stderr, flush=True)


# The private Airflow bridge returns these typed messages as safe JSON, never raw logs.
LOG_SINK = ContextVar('platform_notification_sink', default=None)
DELIVERY_BUDGET = ContextVar('platform_notification_budget', default=None)


def select_provider(name='log'):
    if name != 'log':
        raise InvalidProviderConfiguration('Unsupported provider')
    return LogTransport()


def deliver(transport, message, *, sleep=time.sleep):
    for attempt in range(1,4):
        try:
            transport.send(message)
            return 'SENT', attempt, 'delivered'
        except TransientDeliveryError:
            if attempt == 3:
                return 'FAILED', attempt, 'transient exhausted'
            sleep(attempt)  # 1s / 2s, transient failures only
        except Exception:
            # Never log provider exceptions, tokens, request headers or DSNs.
            return 'FAILED', attempt, 'provider rejected'
