from __future__ import annotations

from flask import jsonify
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", **extra):
        super().__init__(message)
        self.message, self.status, self.code, self.extra = message, status, code, extra


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return jsonify({"error": e.code, "message": e.message, **e.extra}), e.status

    @app.errorhandler(NotImplementedError)
    def _not_implemented(e: NotImplementedError):
        # Заготовки (голосовые/видео-ответы), включённые флагом раньше времени
        return jsonify({"error": "not_implemented", "message": str(e) or "Ещё не реализовано"}), 501

    @app.errorhandler(IntegrityError)
    def _integrity(e: IntegrityError):
        # Нарушение уникальности/ограничений, не пойманное сервисом явно
        code = getattr(getattr(e, "orig", None), "sqlstate", None) or ""
        if "23505" in str(code) or "unique" in str(e.orig).lower():
            return jsonify({"error": "already_exists", "message": "Такая запись уже есть"}), 409
        return jsonify({"error": "constraint_violation", "message": "Данные не прошли проверку"}), 400

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        return jsonify({"error": e.name.lower().replace(" ", "_"), "message": e.description}), e.code
