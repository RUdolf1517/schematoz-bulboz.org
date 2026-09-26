from __future__ import annotations

from flask import jsonify
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", **extra):
        super().__init__(message)
        self.message, self.status, self.code, self.extra = message, status, code, extra


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return jsonify({"error": e.code, "message": e.message, **e.extra}), e.status

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        return jsonify({"error": e.name.lower().replace(" ", "_"), "message": e.description}), e.code
