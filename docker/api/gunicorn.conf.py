"""Conservative local WSGI serving; access logs omit query strings and headers."""
bind = "0.0.0.0:8000"
workers = 2
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
access_log_format = '%(m)s %(U)s status=%(s)s duration=%(L)s'
