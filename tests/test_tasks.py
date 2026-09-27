"""Задания за «Деревянные»: эскроу, отклики, зачёт/отказ, спор, автозачёт, возврат остатка."""
from datetime import timedelta

from tests.test_kombucha import _db, _give_wood

from app.models import Task, TaskSubmission
from tests.conftest import pass_captcha


def _bal(c):
    return c.get("/api/wallet").get_json()["balance"]


def _new_task(c, **kw):
    data = {"title": "Нарисуй мем про ЕГЭ", "body": "Нужен смешной мем про пробник по профильной математике",
            "proof": "Ссылка на картинку", "reward": 50, "slots": 2, "days": 3, **kw}
    return c.post("/api/tasks", json=data)


def test_task_full_cycle(app, make_user):
    ca, a = make_user()
    c1, u1 = make_user()
    c2, u2 = make_user()
    c3, u3 = make_user()
    assert _new_task(ca).get_json()["error"] == "not_enough_wood"
    _give_wood(app, a["id"], 1000)
    b0 = _bal(ca)
    assert _new_task(ca, reward=1).status_code == 400
    r = _new_task(ca)
    assert r.status_code == 201, r.json
    t = r.get_json()["task"]
    assert _bal(ca) == b0 - 100 - 10                        # 2 × 50 + 10% комиссии
    assert any(x["id"] == t["id"] for x in c1.get("/api/tasks").get_json()["items"])
    assert ca.post(f"/api/tasks/{t['id']}/submit", json={"body": "сам"}).get_json()["error"] == "own_task"
    s1 = c1.post(f"/api/tasks/{t['id']}/submit", json={"body": "https://img.example/1.png"}).get_json()["submission"]
    pass_captcha(c1)   # все тест-клиенты с одного IP — антиспам мог пометить «подозрительным»
    assert c1.post(f"/api/tasks/{t['id']}/submit", json={"body": "ещё"}).get_json()["error"] == "already_submitted"
    s2 = c2.post(f"/api/tasks/{t['id']}/submit", json={"body": "https://img.example/2.png"}).get_json()["submission"]
    # автор видит все отклики, посторонний — только засчитанные
    assert len(ca.get(f"/api/tasks/{t['id']}").get_json()["submissions"]) == 2
    assert c3.get(f"/api/tasks/{t['id']}").get_json()["submissions"] == []
    assert c1.post(f"/api/task-submissions/{s1['id']}/approve", json={}).status_code == 403
    w1 = _bal(c1)
    assert ca.post(f"/api/task-submissions/{s1['id']}/approve", json={}).status_code == 200
    assert _bal(c1) == w1 + 50
    # отказ без причины нельзя; с причиной — можно; исполнитель спорит, модератор засчитывает
    assert ca.post(f"/api/task-submissions/{s2['id']}/reject", json={}).status_code == 400
    assert ca.post(f"/api/task-submissions/{s2['id']}/reject", json={"reason": "Не смешно"}).status_code == 200
    assert c2.post(f"/api/task-submissions/{s2['id']}/dispute", json={}).get_json()["submission"]["status"] == "disputed"
    cm, _ = make_user("moderator")
    assert any(x["id"] == s2["id"] for x in cm.get("/api/mod/task-disputes").get_json()["items"])
    w2 = _bal(c2)
    assert cm.post(f"/api/mod/task-submissions/{s2['id']}/approve", json={"comment": "смешно же"}).status_code == 200
    assert _bal(c2) == w2 + 50
    d = ca.get(f"/api/tasks/{t['id']}").get_json()["task"]
    assert d["status"] == "done" and d["slots_left"] == 0 and d["refunded"] == 0
    assert c3.post(f"/api/tasks/{t['id']}/submit", json={"body": "поздно"}).get_json()["error"] == "task_closed"
    badges = {b["code"] for b in c1.get(f"/api/users/{u1['username']}").get_json()["badges"]}
    assert "task_done" in badges
    kinds = [n["kind"] for n in ca.get("/api/notifications").get_json()["items"]]
    assert "task" in kinds


def test_task_close_refund_and_auto_approve(app, make_user):
    ca, a = make_user()
    c1, u1 = make_user()
    _give_wood(app, a["id"], 1000)
    t = _new_task(ca, reward=100, slots=3).get_json()["task"]
    b_after = _bal(ca)
    sub = c1.post(f"/api/tasks/{t['id']}/submit", json={"body": "готово"}).get_json()["submission"]

    async def age(s):
        x = await s.get(TaskSubmission, sub["id"])
        x.created_at -= timedelta(hours=73)
    _db(app, age)
    w1 = _bal(c1)
    d = c1.get(f"/api/tasks/{t['id']}").get_json()
    assert d["task"]["my_submission"]["status"] == "approved"   # автор молчал 72 ч — засчитано
    assert _bal(c1) == w1 + 100
    r = ca.post(f"/api/tasks/{t['id']}/close", json={}).get_json()
    assert r["task"]["status"] == "closed" and r["task"]["refunded"] == 200
    assert _bal(ca) == b_after + 200                              # комиссия не возвращается


def test_task_expiry_waits_for_pending(app, make_user):
    ca, a = make_user()
    c1, _ = make_user()
    _give_wood(app, a["id"], 1000)
    t = _new_task(ca, reward=10, slots=2).get_json()["task"]
    sub = c1.post(f"/api/tasks/{t['id']}/submit", json={"body": "готово"}).get_json()["submission"]

    async def expire(s):
        x = await s.get(Task, t["id"])
        x.deadline -= timedelta(days=5)
    _db(app, expire)
    d = ca.get(f"/api/tasks/{t['id']}").get_json()["task"]
    assert d["status"] == "expired" and d["refunded"] is None       # ждём решения по отклику
    ca.post(f"/api/task-submissions/{sub['id']}/reject", json={"reason": "не то"})
    d = ca.get(f"/api/tasks/{t['id']}").get_json()["task"]
    assert d["refunded"] == 20


def test_mod_removes_task(app, make_user):
    ca, a = make_user()
    c1, _ = make_user()
    cm, _ = make_user("moderator")
    _give_wood(app, a["id"], 1000)
    t = _new_task(ca, reward=10, slots=1).get_json()["task"]
    c1.post(f"/api/tasks/{t['id']}/submit", json={"body": "x" * 5})
    assert c1.post(f"/api/mod/tasks/{t['id']}/remove", json={}).status_code == 403
    r = cm.post(f"/api/mod/tasks/{t['id']}/remove", json={"reason": "спам"}).get_json()
    assert r["task"]["status"] == "removed" and r["task"]["refunded"] == 10
    assert c1.get(f"/api/tasks/{t['id']}").status_code == 404
