"""Админка (JSON API): /admin/*"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, request
from sqlalchemy import delete, func, select

from ..auth.rbac import invalidate_perms, require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import (
    Answer, Category, LegalPage, LegalPageVersion, ModAction, Question, Report, ReportStatus,
    Role, Room, Setting, User, UserRole,
)
from ..moderation import modlog_out
from ..services.captcha import invalidate_captcha_settings, validate_captcha_settings
from ..services.features import get_features, invalidate_features
from ..services.modlog import log_action
from ..api.utils import json_body, req_str

bp = Blueprint("admin", __name__, url_prefix="/admin")

SETTING_PERMS = {"captcha": "settings.captcha", "antispam": "settings.antispam",
                 "features": "settings.features"}


@bp.put("/users/<int:uid>/roles")
@require_perm("role.assign")
async def set_roles(uid: int):
    codes = json_body().get("roles")
    if not isinstance(codes, list) or "user" not in codes:
        raise ApiError("roles — список, роль 'user' обязательна", 400, "validation_error")
    if uid == g.user.id and "admin" not in codes:
        raise ApiError("Нельзя снять админку с самого себя", 400, "self_demote")
    async with session_scope() as s:
        if await s.get(User, uid) is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        roles = (await s.scalars(select(Role).where(Role.code.in_(codes)))).all()
        if len(roles) != len(set(codes)):
            raise ApiError("Неизвестная роль", 400, "unknown_role")
        await s.execute(delete(UserRole).where(UserRole.user_id == uid))
        for r in roles:
            s.add(UserRole(user_id=uid, role_id=r.id, granted_by=g.user.id))
        log_action(s, g.user.id, "role.set", "user", uid, roles=sorted(codes))
    invalidate_perms(uid)
    return {"ok": True, "roles": sorted(codes)}


@bp.post("/categories")
@require_perm("category.manage")
async def create_category():
    data = json_body()
    async with session_scope() as s:
        c = Category(slug=req_str(data, "slug", max_len=64), title=req_str(data, "title", max_len=128),
                     parent_id=data.get("parent_id"), sort=data.get("sort", 0))
        s.add(c)
        await s.flush()
        log_action(s, g.user.id, "category.create", "category", c.id, slug=c.slug)
    return {"id": c.id}, 201


@bp.post("/rooms")
@require_perm("room.manage")
async def create_room():
    data = json_body()
    async with session_scope() as s:
        r = Room(slug=req_str(data, "slug", max_len=64), title=req_str(data, "title", max_len=128),
                 description=data.get("description"), category_id=data.get("category_id"),
                 is_official=bool(data.get("is_official", True)))
        s.add(r)
        await s.flush()
        log_action(s, g.user.id, "room.create", "room", r.id, slug=r.slug)
    return {"id": r.id}, 201


@bp.get("/settings/<key>")
async def get_setting(key: str):
    perm = SETTING_PERMS.get(key)
    if perm is None:
        raise ApiError("Неизвестная настройка", 404, "not_found")

    @require_perm(perm)
    async def _do():
        if key == "features":
            return {"key": key, "value": await get_features()}
        async with session_scope() as s:
            row = await s.get(Setting, key)
        value = row.value if row else {}
        if key == "captcha":
            cfg = current_app.config
            value = {"categories": cfg["KREMLE_CATEGORIES"], "question_count": cfg["KREMLE_QUESTION_COUNT"],
                     "max_errors": cfg["KREMLE_MAX_ERRORS"], **value}
        return {"key": key, "value": value}
    return await _do()


@bp.get("/users")
@require_perm("role.assign")
async def search_users():
    q = (request.args.get("q") or "").strip().lower()
    async with session_scope() as s:
        stmt = select(User).order_by(User.id).limit(20)
        if q:
            stmt = stmt.where(User.username.contains(q, autoescape=True) | User.email.contains(q, autoescape=True))
        users = (await s.scalars(stmt)).all()
    return {"items": [{"id": u.id, "username": u.username, "email": u.email,
                       "reputation": u.reputation, "roles": sorted(r.code for r in u.roles),
                       "created_at": u.created_at.isoformat()} for u in users]}


@bp.put("/settings/<key>")
async def put_setting(key: str):
    perm = SETTING_PERMS.get(key)
    if perm is None:
        raise ApiError("Неизвестная настройка", 404, "not_found")

    @require_perm(perm)
    async def _do():
        value = json_body().get("value")
        if not isinstance(value, dict):
            raise ApiError("value — объект", 400, "validation_error")
        if key == "captcha":
            value = validate_captcha_settings(value)
        if key == "features":
            bad = [k for k, v in value.items()
                   if k not in current_app.config["FEATURES"] or not isinstance(v, bool)]
            if bad:
                raise ApiError(f"Неизвестные флаги: {', '.join(bad)}", 400, "validation_error")
        async with session_scope() as s:
            row = await s.get(Setting, key, with_for_update=True)
            old = row.value if row else None
            if row is None:
                s.add(Setting(key=key, value=value, updated_by=g.user.id))
            else:
                row.value, row.updated_by = value, g.user.id
            log_action(s, g.user.id, "settings.update", "setting", None, key=key, old=old, new=value)
        if key == "features":
            invalidate_features()
        if key == "captcha":
            invalidate_captcha_settings()
        return {"key": key, "value": value}
    return await _do()


@bp.put("/legal/<slug>")
@require_perm("legal.edit")
async def edit_legal(slug: str):
    data = json_body()
    body = req_str(data, "body_md", max_len=200_000)
    async with session_scope() as s:
        page = await s.scalar(select(LegalPage).where(LegalPage.slug == slug).with_for_update())
        if page is None:
            raise ApiError("Страница не найдена", 404, "not_found")
        page.current_version += 1
        if data.get("title"):
            page.title = data["title"][:128]
        s.add(LegalPageVersion(page_id=page.id, version=page.current_version, body_md=body,
                               edited_by=g.user.id))
        log_action(s, g.user.id, "legal.edit", "legal_page", page.id, slug=slug,
                   version=page.current_version)
        ver = page.current_version
    return {"slug": slug, "version": ver}


@bp.get("/legal/<slug>/versions")
@require_perm("legal.edit")
async def legal_versions(slug: str):
    async with session_scope() as s:
        rows = (await s.execute(
            select(LegalPageVersion).join(LegalPage, LegalPage.id == LegalPageVersion.page_id)
            .where(LegalPage.slug == slug).order_by(LegalPageVersion.version.desc())
        )).scalars().all()
    return {"items": [{"version": v.version, "edited_by": v.edited_by,
                       "created_at": v.created_at.isoformat(), "body_md": v.body_md} for v in rows]}


@bp.get("/modlog")
@require_perm("modlog.read_all")
async def modlog():
    actor = request.args.get("actor_id", type=int)
    async with session_scope() as s:
        stmt = select(ModAction).order_by(ModAction.id.desc()).limit(200)
        if actor:
            stmt = stmt.where(ModAction.actor_id == actor)
        rows = (await s.scalars(stmt)).all()
    return {"items": [modlog_out(a) for a in rows]}


@bp.get("/analytics")
@require_perm("analytics.read")
async def analytics():
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    async with session_scope() as s:
        async def count(stmt):
            return await s.scalar(stmt)
        return {
            "users_total": await count(select(func.count(User.id))),
            "users_24h": await count(select(func.count(User.id)).where(User.created_at >= day_ago)),
            "dau": await count(select(func.count(User.id)).where(User.last_seen_at >= day_ago)),
            "questions_24h": await count(select(func.count(Question.id)).where(Question.created_at >= day_ago)),
            "answers_24h": await count(select(func.count(Answer.id)).where(Answer.created_at >= day_ago)),
            "reports_open": await count(select(func.count(Report.id)).where(Report.status == ReportStatus.OPEN)),
        }
