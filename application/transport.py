"""HTTP-only concerns. No SQL, connection strings or driver exception text."""
import logging
import re
from functools import wraps

from django.core.exceptions import DisallowedHost, SuspiciousOperation
from django.http import JsonResponse
from application.errors import ApiError
from application.serialization import json_value

logger = logging.getLogger("football_api")


def response(data, status=200):
    return JsonResponse(json_value(data), status=status, json_dumps_params={"allow_nan": False, "ensure_ascii": False})


def error_response(code, message, status):
    return response({"error": {"code": code, "message": message}}, status)


def endpoint(function):
    @wraps(function)
    def wrapped(request, *args, **kwargs):
        if request.method != "GET":
            result = error_response("method_not_allowed", "Only GET is supported", 405)
            result["Allow"] = "GET"
            return result
        try:
            return response(function(request, *args, **kwargs))
        except SuspiciousOperation:
            return error_response("invalid_request", "Invalid request", 400)
        except ApiError as exc:
            if exc.status >= 500:
                logger.warning("API failure code=%s", exc.code)
            return error_response(exc.code, exc.message, exc.status)
        except Exception as exc:
            logger.error("API failure exception=%s", type(exc).__name__)
            return error_response("server_error", "Unexpected server error", 500)
    return wrapped


def uint(value, name, bits=64):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value) or not 0 < int(value) < 2 ** bits:
        raise ApiError("invalid_request", f"{name} must be a positive UInt{bits}", 400)
    return int(value)


def parameters(request, *, allow_team=False):
    allowed = {"team_id"} if allow_team else set()
    if set(request.GET) - allowed or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise ApiError("invalid_request", "Unsupported or repeated query parameter", 400)
    return uint(request.GET["team_id"], "team_id", 32) if "team_id" in request.GET else None


def pass_parameters(request):
    allowed = {'team_id', 'player_id', 'period'}
    if set(request.GET) - allowed or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise ApiError('invalid_request', 'Unsupported or repeated query parameter', 400)
    result = {name: uint(request.GET[name], name, 8 if name == 'period' else 32) for name in request.GET}
    if result.get('period', 1) > 5:
        raise ApiError('invalid_request', 'period must be between 1 and 5', 400)
    return result


def not_found(request, exception=None):
    return error_response("not_found", "Endpoint was not found", 404)


def bad_request(request, exception=None):
    return error_response("invalid_request", "Invalid request", 400)


def server_error(request):
    return error_response("server_error", "Unexpected server error", 500)


class ApiMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            request.get_host()
        except DisallowedHost:
            return bad_request(request)
        result = self.get_response(request)
        result["Cache-Control"] = "no-store"
        return result
