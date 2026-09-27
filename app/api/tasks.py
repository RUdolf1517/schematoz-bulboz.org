"""API заданий за «Деревянные». Логика — services/tasks.py."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import func, select

from ..auth.rbac import login_required, require_perm
from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import Task, TaskSubmission, User
from ..services import antispam
from ..services import tasks as ts
from ..services import wood
from ..services.captcha import captcha_required
from ..services.markdown import render as render_md
from . import bp
from .utils import account_age_hours, json_body, user_public


def _int(data: dict, key: str, lo: int, hi: int) -> int:
    v = data.get(key)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ApiError(f"{key}: целое от {lo} до {hi}", 400, "validation_error", field=key)
    return v


def _str(data: dict, key: str, lo: int, hi: int) -> str:
    v = str(data.get(key) or "").strip()
    if not lo <= len(v) <= hi:
        raise ApiError(f"{key}: от {lo} до {hi} символов", 400, "validation_error", field=key)
    return v


def _task_out(t: Task, author: User, pending: int = 0, mine: dict | None = None) -> dict:
    return {"id": t.id, "title": t.title, "body": t.body, "body_html": render_md(t.body), "proof": t.proof,
            "reward": t.reward, "slots": t.slots, "slots_left": t.slots_left, "done": t.slots - t.slots_left,
            "status": t.status, "deadline": t.deadline.isoformat(), "created_at": t.created_at.isoformat(),
            "refunded": t.refunded, "fee": t.fee, "author": user_public(author), "pending": pending,
            "my_submission": mine}


def _sub_out(x: TaskSubmission, u: User) -> dict:
    return {"id": x.id, "body": x.body, "body_html": render_md(x.body), "status": x.status, "reason": x.reason,
            "created_at": x.created_at.isoformat(), "decided_at": x.decided_at.isoformat() if x.decided_at else None,
            "user": user_public(u)}


@bp.get("/tasks")
async def tasks_list():
    """?tab=open|mine|doing. open — открытые (сначала дорогие или новые: sort=new|reward)."""
    tab = request.args.get("tab", "open")
    sort = request.args.get("sort", "new")
    uid = current_user_id()
    async with session_scope() as s:
        await ts.settle_open(s)
        q = select(Task, User).join(User, User.id == Task.author_id)
        if tab == "mine" and uid:
            q = q.where(Task.author_id == uid)
        elif tab == "doing" and uid:
            q = q.where(Task.id.in_(select(TaskSubmission.task_id).where(TaskSubmission.user_id == uid)))
        else:
            q = q.where(Task.status == "open")
        q = q.order_by(Task.reward.desc() if sort == "reward" else Task.id.desc()).limit(100)
        rows = (await s.execute(q)).all()
        ids = [t.id for t, _ in rows] or [0]
        pend = dict((await s.execute(select(TaskSubmission.task_id, func.count()).where(
            TaskSubmission.task_id.in_(ids), TaskSubmission.status.in_(ts.PENDING)).group_by(TaskSubmission.task_id))).all())
        mine = {}
        if uid:
            mine = {x.task_id: {"id": x.id, "status": x.status, "reason": x.reason} for x in (await s.scalars(
                select(TaskSubmission).where(TaskSubmission.task_id.in_(ids), TaskSubmission.user_id == uid))).all()}
    return {"items": [_task_out(t, a, pend.get(t.id, 0), mine.get(t.id)) for t, a in rows],
            "rules": {"fee": ts.FEE, "min_reward": ts.MIN_REWARD, "max_reward": ts.MAX_REWARD, "max_slots": ts.MAX_SLOTS,
                      "min_days": ts.MIN_DAYS, "max_days": ts.MAX_DAYS, "auto_approve_hours": 72,
                      "max_open": ts.MAX_OPEN_PER_USER}}


@bp.post("/tasks")
@require_perm("answer.create")
@captcha_required()
async def task_create():
    data = json_body()
    title = _str(data, "title", 5, 120)
    body = _str(data, "body", 10, 2000)
    proof = str(data.get("proof") or "").strip()[:300]
    reward = _int(data, "reward", ts.MIN_REWARD, ts.MAX_REWARD)
    slots = _int(data, "slots", 1, ts.MAX_SLOTS)
    days = _int(data, "days", ts.MIN_DAYS, ts.MAX_DAYS)
    antispam.check_post(title + "\n" + body, account_age_hours(g.user))
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        t = await ts.create(s, user, title, body, proof, reward, slots, days)
        await s.flush()
        await s.refresh(t)
        return {"task": _task_out(t, user), "wood": await wood.balance(s, user.id)}, 201


@bp.get("/tasks/<int:tid>")
async def task_get(tid: int):
    uid = current_user_id()
    async with session_scope() as s:
        t = await s.get(Task, tid, with_for_update=True)
        if t is None:
            raise ApiError("Задание не найдено", 404, "not_found")
        await ts.settle(s, t)
        author = await s.get(User, t.author_id)
        q = select(TaskSubmission, User).join(User, User.id == TaskSubmission.user_id).where(TaskSubmission.task_id == tid)
        is_author = uid == t.author_id
        is_mod = False
        if uid and not is_author:
            from ..auth.rbac import get_user_perms
            is_mod = "content.hide" in await get_user_perms(uid)
        if not is_author and not is_mod:
            # чужим видны только засчитанные (как витрина), себе — свой отклик
            q = q.where((TaskSubmission.status == "approved") | (TaskSubmission.user_id == (uid or 0)))
        subs = (await s.execute(q.order_by(TaskSubmission.id))).all()
        pending = await ts._pending_count(s, t)
        mine = next(({"id": x.id, "status": x.status, "reason": x.reason} for x, _ in subs if x.user_id == uid), None)
        if t.status == "removed" and not (is_author or is_mod):
            raise ApiError("Задание снято модератором", 404, "not_found")
        return {"task": _task_out(t, author, pending, mine), "is_author": is_author, "is_mod": is_mod,
                "submissions": [_sub_out(x, u) for x, u in subs]}


async def _load(s, tid: int) -> Task:
    t = await s.get(Task, tid, with_for_update=True)
    if t is None:
        raise ApiError("Задание не найдено", 404, "not_found")
    return t


async def _load_sub(s, sid: int) -> tuple[Task, TaskSubmission]:
    sub = await s.get(TaskSubmission, sid, with_for_update=True)
    if sub is None:
        raise ApiError("Отклик не найден", 404, "not_found")
    return await _load(s, sub.task_id), sub


@bp.post("/tasks/<int:tid>/submit")
@require_perm("answer.create")
@captcha_required()
async def task_submit(tid: int):
    body = _str(json_body(), "body", 3, 1000)
    antispam.check_post(body, account_age_hours(g.user))
    async with session_scope() as s:
        t = await _load(s, tid)
        user = await s.get(User, g.user.id)
        sub = await ts.submit(s, user, t, body)
        await s.flush()
        await s.refresh(sub)
        return {"submission": _sub_out(sub, user)}, 201


@bp.post("/tasks/<int:tid>/close")
@login_required
async def task_close(tid: int):
    async with session_scope() as s:
        t = await _load(s, tid)
        await ts.close(s, g.user, t)
        return {"task": {"id": t.id, "status": t.status, "refunded": t.refunded}}


@bp.post("/task-submissions/<int:sid>/<any(approve, reject, dispute):op>")
@login_required
async def submission_decide(sid: int, op: str):
    reason = str(json_body().get("reason") or "").strip() or None
    async with session_scope() as s:
        t, sub = await _load_sub(s, sid)
        if op == "dispute":
            await ts.dispute(s, g.user, t, sub)
        else:
            await ts.decide(s, g.user, t, sub, op == "approve", reason)
        return {"submission": {"id": sub.id, "status": sub.status},
                "task": {"id": t.id, "status": t.status, "slots_left": t.slots_left, "refunded": t.refunded}}


# ---------------------------------------------------------------- модерация
@bp.get("/mod/task-disputes")
@require_perm("content.hide")
async def task_disputes():
    async with session_scope() as s:
        rows = (await s.execute(select(TaskSubmission, Task, User).join(Task, Task.id == TaskSubmission.task_id)
                                .join(User, User.id == TaskSubmission.user_id)
                                .where(TaskSubmission.status == "disputed").order_by(TaskSubmission.id))).all()
    return {"items": [{**_sub_out(x, u), "task": {"id": t.id, "title": t.title, "proof": t.proof, "reward": t.reward}}
                      for x, t, u in rows]}


@bp.post("/mod/task-submissions/<int:sid>/<any(approve, reject):op>")
@require_perm("content.hide")
async def task_dispute_resolve(sid: int, op: str):
    comment = str(json_body().get("comment") or "").strip()[:200] or None
    async with session_scope() as s:
        t, sub = await _load_sub(s, sid)
        await ts.resolve_dispute(s, t, sub, op == "approve", comment)
        return {"submission": {"id": sub.id, "status": sub.status}}


@bp.post("/mod/tasks/<int:tid>/remove")
@require_perm("content.hide")
async def task_remove(tid: int):
    reason = str(json_body().get("reason") or "нарушение правил").strip()[:200]
    async with session_scope() as s:
        t = await _load(s, tid)
        await ts.remove(s, t, reason)
        return {"task": {"id": t.id, "status": t.status, "refunded": t.refunded}}
