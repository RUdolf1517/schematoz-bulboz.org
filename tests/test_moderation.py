import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_report_hide_and_modlog(qa, make_user):
    mod_c, mod = make_user("moderator")
    admin_c, _ = make_user("admin")
    aid = qa["a"]["id"]
    r = qa["other_c"].post("/api/reports", json={"target_type": "answer", "target_id": aid,
                                                  "reason": "self_harm"})
    assert r.status_code == 201
    assert qa["other_c"].post("/api/reports", json={"target_type": "answer", "target_id": aid,
                                                     "reason": "spam"}).status_code == 409
    qa["author_c"].post("/api/reports", json={"target_type": "answer", "target_id": aid, "reason": "spam"})

    queue = mod_c.get("/mod/reports").json["items"]
    assert queue[0]["reason"] == "self_harm"  # приоритет P0 наверху
    r = mod_c.post(f"/mod/reports/{queue[0]['id']}/resolve", json={"decision": "hide"})
    assert r.status_code == 200 and r.json["closed"] == 2
    answers = qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json["answers"]
    assert answers == []

    own = [a["action"] for a in mod_c.get("/mod/log").json["items"]]
    assert "content.hide" in own and "report.hide" in own
    full = admin_c.get("/admin/modlog").json["items"]
    assert {a["actor_id"] for a in full} == {mod["id"]}

    assert mod_c.post(f"/mod/content/answer/{aid}/restore").status_code == 200
    assert len(qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json["answers"]) == 1


def test_ban_blocks_and_revokes_session(make_user):
    mod_c, _ = make_user("moderator")
    victim_c, victim = make_user()
    r = mod_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "спам", "days": 7})
    assert r.status_code == 201
    assert victim_c.post("/api/questions", json={"title": "Я вернулся?"}).status_code == 401


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
