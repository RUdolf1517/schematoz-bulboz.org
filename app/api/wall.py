"""Стена в профиле: писать может любой вошедший (кроме забаненных), до 500 символов.
Удалить запись — автор, хозяин стены или модератор (content.hide). Хозяин может закрыть стену в настройках."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import select

from ..auth.rbac import require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import User, WallPost
from ..services import antispam, wood
from ..services.captcha import captcha_required
from ..services.markdown import render as render_md
from ..services.notifications import notify
from . import bp
from ..auth.sessions import current_user_id
from .utils import account_age_hours, json_body, user_public

MAX_LEN = 500


def _out(p: WallPost, author: User, viewer: int | None, owner_id: int, can_mod: bool = False) -> dict:
    return {"id": p.id, "body": p.body, "body_html": render_md(p.body), "created_at": p.created_at.isoformat(),
            "author": user_public(author),
            "can_delete": viewer is not None and (viewer in (p.author_id, owner_id) or can_mod)}


async def _owner(s, username: str) -> User:
    u = await s.scalar(select(User).where(User.username == username.lower()))
    if u is None:
        raise ApiError("Пользователь не найден", 404, "not_found")
    return u


@bp.get("/users/<username>/wall")
async def wall_get(username: str):
    before = request.args.get("before", type=int)
    viewer = current_user_id()
    async with session_scope() as s:
        owner = await _owner(s, username)
        q = (select(WallPost, User).join(User, User.id == WallPost.author_id)
             .where(WallPost.owner_id == owner.id, WallPost.deleted.is_(False)))
        if before:
            q = q.where(WallPost.id < before)
        rows = (await s.execute(q.order_by(WallPost.id.desc()).limit(30))).all()
        can_mod = False
        if viewer:
            from ..auth.rbac import get_user_perms
            can_mod = "content.hide" in await get_user_perms(viewer)
    closed = bool((owner.profile or {}).get("wall_closed"))
    if "wall" in ((owner.profile or {}).get("hidden_sections") or []) and viewer != owner.id:
        rows = []
    return {"items": [_out(p, a, viewer, owner.id, can_mod) for p, a in rows],
            "next_before": rows[-1][0].id if len(rows) == 30 else None,
            "closed": closed, "can_post": viewer is not None and (not closed or viewer == owner.id)}


@bp.post("/users/<username>/wall")
@require_perm("answer.create")
@captcha_required()
async def wall_post(username: str):
    body = str(json_body().get("body") or "").strip()
    if not 1 <= len(body) <= MAX_LEN:
        raise ApiError(f"Запись: 1–{MAX_LEN} символов", 400, "validation_error", field="body")
    antispam.check_post(body, account_age_hours(g.user))
    async with session_scope() as s:
        owner = await _owner(s, username)
        if (owner.profile or {}).get("wall_closed") and owner.id != g.user.id:
            raise ApiError("Хозяин закрыл стену", 403, "wall_closed")
        p = WallPost(owner_id=owner.id, author_id=g.user.id, body=body)
        s.add(p)
        await s.flush()
        await s.refresh(p)
        if owner.id != g.user.id:
            await wood.earn(s, g.user.id, "wall_post", p.id)
            from ..services.kombucha_achievements import award
            await award(s, g.user.id, "wall_first")
            notify(s, owner.id, "wall", username=g.user.username, post_id=p.id, preview=body[:80])
        author = await s.get(User, g.user.id)
        return {"post": _out(p, author, g.user.id, owner.id)}, 201


@bp.delete("/wall/<int:pid>")
@require_perm("answer.create")
async def wall_delete(pid: int):
    async with session_scope() as s:
        p = await s.get(WallPost, pid, with_for_update=True)
        if p is None or p.deleted:
            raise ApiError("Запись не найдена", 404, "not_found")
        if g.user.id not in (p.author_id, p.owner_id) and "content.hide" not in g.perms:
            raise ApiError("Нельзя удалить чужую запись", 403, "forbidden")
        p.deleted = True
    return {"ok": True}
