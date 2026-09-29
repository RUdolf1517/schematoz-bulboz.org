import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_mod_user_search_ban_lift_and_modlog(make_user):
    mod_c, mod = make_user("moderator")
    admin_c, _ = make_user("admin")
    _, v = make_user(username="griboed_42")
    assert mod_c.get("/mod/users?q=g").json["items"] == []
    items = mod_c.get("/mod/users?q=griboed").json["items"]
    assert [u["username"] for u in items] == ["griboed_42"] and items[0]["ban"] is None
    ban_id = mod_c.post("/mod/bans", json={"user_id": v["id"], "reason": "автокликер", "days": 3}).json["ban_id"]
    assert mod_c.get("/mod/users?q=griboed").json["items"][0]["ban"]["id"] == ban_id
    assert mod_c.post(f"/mod/bans/{ban_id}/lift").status_code == 200
    assert mod_c.get("/mod/users?q=griboed").json["items"][0]["ban"] is None
    own = [a["action"] for a in mod_c.get("/mod/log").json["items"]]
    assert own == ["ban.lift", "ban.issue"]
    assert {a["actor_id"] for a in admin_c.get("/admin/modlog").json["items"]} == {mod["id"]}


def test_ban_blocks_and_revokes_session(make_user):
    mod_c, _ = make_user("moderator")
    victim_c, victim = make_user()
    r = mod_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "спам", "days": 7})
    assert r.status_code == 201
    assert victim_c.post("/api/trades", json={}).status_code == 401   # сессии отозваны


def test_admin_permanent_ban_and_roles(make_user):
    admin_c, _ = make_user("admin")
    c, u = make_user()
    assert admin_c.post("/mod/bans", json={"user_id": u["id"], "reason": "x", "days": None}).status_code == 201
    _, u2 = make_user()
    r = admin_c.put(f"/admin/users/{u2['id']}/roles", json={"roles": ["user", "moderator"]})
    assert r.status_code == 200


def test_modlog_is_append_only(app, make_user):
    mod_c, _ = make_user("moderator")
    _, v = make_user()
    mod_c.post("/mod/bans", json={"user_id": v["id"], "reason": "x", "days": 1})
    from app.db import session_scope

    async def tamper():
        async with session_scope() as s:
            await s.execute(text("DELETE FROM mod_actions"))

    with app.app_context():
        with pytest.raises(DBAPIError):
            asyncio.run(tamper())
