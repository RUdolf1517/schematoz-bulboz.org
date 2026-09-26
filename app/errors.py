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

    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

    from .dbcheck import db_problem

    def _db_down(e):
        hint = db_problem(e, app.config.get("DATABASE_URL", ""))
        if hint is None:
            raise e  # не проблема подключения — пусть обработается как обычная 500
        if not getattr(app, "_db_hint_logged", False):  # одна понятная строка в лог вместо простыни
            app.logger.error("База данных недоступна:\n   %s", hint)
            app._db_hint_logged = True
        return jsonify({"error": "db_unavailable",
                        "message": "База данных недоступна — сервер настроен не до конца. Подробности в логе сервера."}), 503

    for exc_type in (DBAPIError, OperationalError, InterfaceError, ConnectionRefusedError):
        app.register_error_handler(exc_type, _db_down)

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        return jsonify({"error": e.name.lower().replace(" ", "_"), "message": e.description}), e.code
