from __future__ import annotations

from flask import g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import Answer, Comment, Question, Report, ReportReason, ReportTarget, User
from . import bp
from .utils import json_body

PRIORITY = {ReportReason.SELF_HARM: 100, ReportReason.DOXXING: 90, ReportReason.ILLEGAL: 50,
            ReportReason.BULLYING: 30}
TARGET_MODEL = {ReportTarget.QUESTION: Question, ReportTarget.ANSWER: Answer, ReportTarget.COMMENT: Comment, ReportTarget.USER: User}


@bp.post("/reports")
@require_perm("report.create")
async def create_report():
    data = json_body()
    try:
        target_type = ReportTarget(data.get("target_type"))
        reason = ReportReason(data.get("reason"))
    except ValueError:
        raise ApiError("Некорректный тип цели или причина", 400, "validation_error")
    target_id = data.get("target_id")
    if not isinstance(target_id, int):
        raise ApiError("target_id обязателен", 400, "validation_error", field="target_id")
    try:
        async with session_scope() as s:
            if await s.get(TARGET_MODEL[target_type], target_id) is None:
                raise ApiError("Объект не найден", 404, "not_found")
            r = Report(reporter_id=g.user.id, target_type=target_type, target_id=target_id,
                       reason=reason, comment=(data.get("comment") or None),
                       priority=PRIORITY.get(reason, 0))
            s.add(r)
            await s.flush()
            rid = r.id
    except IntegrityError:
        raise ApiError("Ты уже жаловался на это", 409, "already_reported")
    return {"report_id": rid}, 201
