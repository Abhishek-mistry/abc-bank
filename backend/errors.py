from flask import jsonify, request
from werkzeug.exceptions import HTTPException

ERROR_STATUS = {
    "VALIDATION_ERROR": 400, "AUTH_REQUIRED": 401, "INVALID_CREDENTIALS": 401, "FORBIDDEN": 403,
    "NOT_FOUND": 404, "ACCOUNT_NOT_FOUND": 404, "METHOD_NOT_ALLOWED": 405,
    "USERNAME_TAKEN": 409, "EMAIL_TAKEN": 409, "INVALID_STATE": 409,
    "INSUFFICIENT_FUNDS": 422, "ACCOUNT_NOT_ACTIVE": 422, "SAME_ACCOUNT_TRANSFER": 422, "LIMIT_EXCEEDED": 422,
    "TXN_NOT_REVERSIBLE": 422, "REVERSAL_FUNDS_UNAVAILABLE": 422, "LOAN_INCOMPLETE": 422,
    "INTERNAL_ERROR": 500, "SIMULATED_NETWORK_FAILURE": 503, "TXN_RETRY_EXHAUSTED": 503, "NETWORK_TIMEOUT": 504,
}


class ApiError(Exception):
    def __init__(self, code, message, details=None, http_status=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}
        self.http_status = http_status or ERROR_STATUS.get(code, 500)


class SimulatedNetworkError(Exception):
    def __init__(self, point):
        super().__init__(f"Simulated network failure at {point}")
        self.point = point


class SimulatedResponseDropped(Exception):
    pass


def _err(code, message, status, details=None):
    resp = jsonify({"success": False, "error": {"code": code, "message": message, "details": details or {}}})
    resp.status_code = status
    return resp


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api(e):
        return _err(e.code, e.message, e.http_status, e.details)

    @app.errorhandler(SimulatedNetworkError)
    def _net(e):
        return _err("SIMULATED_NETWORK_FAILURE", "Network failure. Transaction rolled back; your money is safe.", 503)

    @app.errorhandler(SimulatedResponseDropped)
    def _drop(e):
        return _err("NETWORK_TIMEOUT", "Connection lost after processing.", 504,
                    {"hint": "Outcome unknown. Retry with the same idempotency_key."})

    @app.errorhandler(404)
    def _404(e):
        return _err("NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _405(e):
        return _err("METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _500(e):
        if isinstance(e, HTTPException):  # e.g. malformed JSON body (400), 415 - not our bug
            return _err("VALIDATION_ERROR" if e.code < 500 else "INTERNAL_ERROR", e.description, e.code)
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return _err("INTERNAL_ERROR", "Internal server error", 500)
