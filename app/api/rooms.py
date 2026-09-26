from __future__ import annotations

from flask import g
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from ..auth.rbac import login_required
from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import Category, Room, RoomMember
from . import bp


def room_out(r: Room, category: Category | None = None, joined: bool | None = None) -> dict:
    return {"id": r.id, "slug": r.slug, "title": r.title, "description": r.description,
            "category": {"slug": category.slug, "title": category.title} if category else None,
            "is_official": r.is_official, "member_count": r.member_count, "joined": joined}


@bp.get("/rooms")
async def list_rooms():
    uid = current_user_id()
    async with session_scope() as s:
        rows = (await s.execute(
            select(Room, Category).outerjoin(Category, Category.id == Room.category_id)
            .order_by(Category.sort, Category.id, Room.member_count.desc(), Room.id)
        )).all()
        mine = set()
        if uid:
            mine = set(await s.scalars(select(RoomMember.room_id).where(RoomMember.user_id == uid)))
    return {"items": [room_out(r, c, r.id in mine if uid else None) for r, c in rows]}


async def _room_by_slug(s, slug: str) -> Room:
    room = await s.scalar(select(Room).where(Room.slug == slug))
    if room is None:
        raise ApiError("Комната не найдена", 404, "not_found")
    return room


@bp.get("/rooms/<slug>")
async def get_room(slug: str):
    uid = current_user_id()
    async with session_scope() as s:
        room = await _room_by_slug(s, slug)
        cat = await s.get(Category, room.category_id) if room.category_id else None
        joined = None
        if uid:
            joined = await s.get(RoomMember, (room.id, uid)) is not None
    return {"room": room_out(room, cat, joined)}


@bp.post("/rooms/<slug>/join")
@login_required
async def join_room(slug: str):
    async with session_scope() as s:
        room = await _room_by_slug(s, slug)
        res = await s.execute(insert(RoomMember).values(room_id=room.id, user_id=g.user.id)
                              .on_conflict_do_nothing().returning(RoomMember.room_id))
        if res.scalar() is not None:
            await s.execute(update(Room).where(Room.id == room.id)
                            .values(member_count=Room.member_count + 1))
        await s.refresh(room)
    return {"joined": True, "member_count": room.member_count}


@bp.delete("/rooms/<slug>/join")
@login_required
async def leave_room(slug: str):
    async with session_scope() as s:
        room = await _room_by_slug(s, slug)
        res = await s.execute(delete(RoomMember).where(RoomMember.room_id == room.id,
                                                       RoomMember.user_id == g.user.id))
        if res.rowcount:
            await s.execute(update(Room).where(Room.id == room.id)
                            .values(member_count=Room.member_count - 1))
        await s.refresh(room)
    return {"joined": False, "member_count": room.member_count}


@bp.get("/categories")
async def list_categories():
    async with session_scope() as s:
        rows = (await s.scalars(select(Category).order_by(Category.sort, Category.id))).all()
    return {"items": [{"id": c.id, "slug": c.slug, "title": c.title} for c in rows]}
