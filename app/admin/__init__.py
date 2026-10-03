"""Админка (JSON API): /admin/*"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, request
from sqlalchemy import delete, func, select

from ..auth.rbac import invalidate_perms, require_perm
from ..db import session_scope
from ..errors import ApiError
from ..models import Kombucha, LegalPage, LegalPageVersion, ModAction, Role, Setting, User, UserRole, WoodTx
from ..moderation import modlog_out
from ..services.captcha import invalidate_captcha_settings, validate_captcha_settings
from ..services.modlog import log_action
from ..api.utils import json_body, req_str

bp = Blueprint("admin", __name__, url_prefix="/admin")

SETTING_PERMS = {"captcha": "settings.captcha", "antispam": "settings.antispam"}


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
        await s.flush()
        from ..services.roles import sync_tier
        await sync_tier(s, uid)
    invalidate_perms(uid)
    return {"ok": True, "roles": sorted(codes)}


@bp.get("/settings/<key>")
async def get_setting(key: str):
    perm = SETTING_PERMS.get(key)
    if perm is None:
        raise ApiError("Неизвестная настройка", 404, "not_found")

    @require_perm(perm)
    async def _do():
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
                       "roles": sorted(r.code for r in u.roles),
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
        async with session_scope() as s:
            row = await s.get(Setting, key, with_for_update=True)
            old = row.value if row else None
            if row is None:
                s.add(Setting(key=key, value=value, updated_by=g.user.id))
            else:
                row.value, row.updated_by = value, g.user.id
            log_action(s, g.user.id, "settings.update", "setting", None, key=key, old=old, new=value)
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
            "kombuchas_alive": await count(select(func.count(Kombucha.id)).where(Kombucha.alive.is_(True), Kombucha.frozen.is_(False))),
            "kombuchas_born_24h": await count(select(func.count(Kombucha.id)).where(Kombucha.born_at >= day_ago)),
            "games_24h": await count(select(func.count(WoodTx.id)).where(WoodTx.reason.in_(("minigame", "meditation")), WoodTx.created_at >= day_ago)),
            "wood_earned_24h": await count(select(func.coalesce(func.sum(WoodTx.delta), 0)).where(WoodTx.delta > 0, WoodTx.created_at >= day_ago)),
        }


# ---------------------------------------------------------------- дебаг чайных грибов (только админ)
KB_DEBUG_PERM = "role.assign"   # есть только у роли admin


@bp.get("/kombucha")
@require_perm(KB_DEBUG_PERM)
async def kb_debug_list():
    """Грибы юзера (по умолчанию — свои) + полный каталог мутаций и стадий."""
    from ..models import Kombucha
    from ..services import kombucha as kb
    login = (request.args.get("user") or "").strip().lstrip("@")
    async with session_scope() as s:
        user = g.user
        if login:
            user = (await s.execute(select(User).where(func.lower(User.username) == login.lower()))).scalar()
            if user is None:
                raise ApiError("Пользователь не найден", 404, "not_found")
        items = (await s.execute(select(Kombucha).where(Kombucha.user_id == user.id)
                                 .order_by(Kombucha.id))).scalars().all()
        return {"user": user.username, "items": [kb.out(k) for k in items], "catalog": kb.catalog(),
                "stages": [{"xp": xp, "title": t, "size": sz} for xp, t, sz in kb.STAGES],
                "moods": ["happy", "hungry", "thirsty", "dirty", "sad", "sticky", "moldy", "dead"]}


@bp.patch("/kombucha/<int:kid>")
@require_perm(KB_DEBUG_PERM)
async def kb_debug_edit(kid: int):
    """Поменять гриб в обход правил: стадия (xp), мутации (любые, без лимитов), статы, жив/плесень/лёд.
    Мутации ставятся с serial 0 и пометкой debug — тиражи и коллекции игроков не трогаются."""
    from ..models import Kombucha
    from ..services import kombucha as kb
    data = json_body()
    async with session_scope() as s:
        k = await s.get(Kombucha, kid)
        if k is None:
            raise ApiError("Гриб не найден", 404, "not_found")
        if k.alive and not k.frozen:
            kb.tick(k)          # досчитать убывание до «сейчас», дальше правим уже актуальные значения
        changed = {}
        if "stage" in data:
            sizes = {sz: xp for xp, _, sz in kb.STAGES}
            if data["stage"] not in sizes:
                raise ApiError("stage — от 1 до 6", 400, "validation_error")
            k.xp = sizes[data["stage"]]
            k.best_xp = max(k.best_xp or 0, k.xp)
            changed["stage"] = data["stage"]
        if "xp" in data:
            k.xp = max(0, int(data["xp"]))
            changed["xp"] = k.xp
        if "mutations" in data:
            codes = data["mutations"]
            if not isinstance(codes, list) or any(c not in kb.MUT_BY_CODE for c in codes):
                raise ApiError("Неизвестная мутация", 400, "validation_error")
            old = {x.get("code"): x for x in (k.mutations or [])}
            at = kb.now().isoformat()
            k.mutations = [old.get(c) or {"code": c, "at": at, "serial": 0, "debug": True}
                           for c in dict.fromkeys(codes)]
            changed["mutations"] = len(k.mutations)
        for st in kb.STATS:
            if st in (data.get("stats") or {}):
                setattr(k, st, float(max(0, min(100, data["stats"][st]))))
                changed[st] = getattr(k, st)
        for flag in ("alive", "mold", "frozen"):
            if flag in data:
                setattr(k, flag, bool(data[flag]))
                changed[flag] = bool(data[flag])
        if all(getattr(k, st) > 0 for st in kb.STATS):
            k.zero_since = None
        if data.get("alive") is True:
            k.died_at, k.zero_since = None, None
        k.cooldowns = {}
        log_action(s, g.user.id, "kombucha.debug", "kombucha", kid, **{c: str(v) for c, v in changed.items()})
        await s.flush()
        return {"kombucha": kb.out(k)}


# ---------------------------------------------------------------- цитаты гриба
QUOTE_PERM = "quotes.edit"


def _quote_out(q) -> dict:
    return {"id": q.id, "kind": q.kind, "text": q.body, "author": q.author, "source": q.source,
            "enabled": q.enabled, "created_at": q.created_at.isoformat() if q.created_at else None}


def _quote_fields(data: dict, partial: bool) -> dict:
    from ..services import quotes
    out = {}
    if "kind" in data or not partial:
        if data.get("kind") not in quotes.KINDS:
            raise ApiError("kind: dubious | philo", 400, "validation_error", field="kind")
        out["kind"] = data["kind"]
    if "text" in data or not partial:
        body = data.get("text")
        body = body.strip() if isinstance(body, str) else ""
        if not 3 <= len(body) <= 400:
            raise ApiError("Цитата — от 3 до 400 символов", 400, "validation_error", field="text")
        if not quotes.is_russian(body):
            raise ApiError("Все цитаты гриба — только на русском", 400, "validation_error", field="text")
        low = body.lower()
        if low.startswith(("как говорил", "как сказал", "процитировал")):
            raise ApiError("Гриб говорит от первого лица — без «как говорил…»", 400, "validation_error", field="text")
        out["body"] = body
    for f, n in (("author", 80), ("source", 120)):
        if f in data:
            v = data.get(f) or ""
            if not isinstance(v, str) or len(v.strip()) > n:
                raise ApiError(f"{f}: строка до {n} символов", 400, "validation_error", field=f)
            out[f] = v.strip()
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            raise ApiError("enabled: true | false", 400, "validation_error", field="enabled")
        out["enabled"] = data["enabled"]
    return out


@bp.get("/quotes")
@require_perm(QUOTE_PERM)
async def quotes_list():
    from ..models import Quote
    from ..services import quotes
    kind = request.args.get("kind")
    async with session_scope() as s:
        stmt = select(Quote).order_by(Quote.id.desc())
        if kind in quotes.KINDS:
            stmt = stmt.where(Quote.kind == kind)
        rows = (await s.scalars(stmt.limit(500))).all()
    return {"items": [_quote_out(q) for q in rows], "kinds": quotes.KINDS,
            "builtin": {"dubious": len(quotes.DUBIOUS), "philo": len(quotes.PHILO)}}


@bp.post("/quotes")
@require_perm(QUOTE_PERM)
async def quotes_create():
    from ..models import Quote
    from ..services import quotes
    f = _quote_fields(json_body(), partial=False)
    async with session_scope() as s:
        q = Quote(created_by=g.user.id, author=f.pop("author", ""), source=f.pop("source", ""), **f)
        s.add(q)
        await s.flush()
        log_action(s, g.user.id, "quote.add", "quote", q.id, kind=q.kind)
        await quotes.refresh_custom(s)
        return {"quote": _quote_out(q)}, 201


@bp.patch("/quotes/<int:qid>")
@require_perm(QUOTE_PERM)
async def quotes_edit(qid: int):
    from ..models import Quote
    from ..services import quotes
    f = _quote_fields(json_body(), partial=True)
    async with session_scope() as s:
        q = await s.get(Quote, qid)
        if q is None:
            raise ApiError("Цитата не найдена", 404, "not_found")
        for k, v in f.items():
            setattr(q, k, v)
        log_action(s, g.user.id, "quote.edit", "quote", qid, fields=sorted(f))
        await s.flush()
        await quotes.refresh_custom(s)
        return {"quote": _quote_out(q)}


@bp.delete("/quotes/<int:qid>")
@require_perm(QUOTE_PERM)
async def quotes_delete(qid: int):
    from ..models import Quote
    from ..services import quotes
    async with session_scope() as s:
        q = await s.get(Quote, qid)
        if q is None:
            raise ApiError("Цитата не найдена", 404, "not_found")
        await s.delete(q)
        log_action(s, g.user.id, "quote.delete", "quote", qid)
        await s.flush()
        await quotes.refresh_custom(s)
    return {"ok": True}
