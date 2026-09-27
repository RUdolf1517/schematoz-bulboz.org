"""Мини-игра «Чайный гриб»."""
import asyncio
from datetime import timedelta

from app.models import Kombucha
from app.services import kombucha as kb


def _shift(app, user_id, hours, **stats):
    """Отмотать время гриба назад (как будто прошло `hours` часов)."""
    from app.db import session_scope

    async def run():
        async with session_scope() as s:
            k = await s.get(Kombucha, user_id)
            k.updated_at = k.updated_at - timedelta(hours=hours)
            k.born_at = k.born_at - timedelta(hours=hours)
            k.cooldowns = {}
            for key, v in stats.items():
                setattr(k, key, v)
    with app.app_context():
        asyncio.run(run())


def test_create_and_actions(make_user):
    c, _ = make_user()
    k = c.get("/api/kombucha").get_json()["kombucha"]
    assert k["alive"] and k["name"] == "Гриша" and k["stage"]["title"] == "Спора"
    r = c.post("/api/kombucha/tea", json={})
    assert r.status_code == 200 and r.get_json()["kombucha"]["stats"]["tea"] == 100
    again = c.post("/api/kombucha/tea", json={})
    assert again.status_code == 429 and again.get_json()["retry_after"] > 3000
    assert c.post("/api/kombucha/hack", json={}).status_code == 404
    assert c.patch("/api/kombucha", json={"name": "Бульбоз"}).get_json()["kombucha"]["name"] == "Бульбоз"
    assert c.patch("/api/kombucha", json={"name": "<script>"}).status_code == 400


def test_oversugar_makes_it_sticky(app, make_user):
    c, u = make_user()
    c.get("/api/kombucha")
    _shift(app, u["id"], 0, sweet=95.0)
    r = c.post("/api/kombucha/sugar", json={}).get_json()
    assert "слипся" in r["message"] and r["kombucha"]["mood"] == "sticky"


def test_decay_and_death_and_restart(app, make_user):
    c, u = make_user()
    c.get("/api/kombucha")
    _shift(app, u["id"], 10)
    k = c.get("/api/kombucha").get_json()["kombucha"]
    assert k["alive"] and k["stats"]["sweet"] < 40
    _shift(app, u["id"], 60)   # всё на нуле гораздо дольше суток
    k = c.get("/api/kombucha").get_json()["kombucha"]
    assert not k["alive"] and k["mood"] == "dead"
    assert c.post("/api/kombucha/tea", json={}).status_code == 409
    k = c.post("/api/kombucha/restart", json={"name": "Гриша II"}).get_json()["kombucha"]
    assert k["alive"] and k["generation"] == 2 and k["xp"] == 0 and k["name"] == "Гриша II"
    assert c.post("/api/kombucha/restart", json={}).status_code == 409


def test_danger_timer(app, make_user):
    c, u = make_user()
    c.get("/api/kombucha")
    _shift(app, u["id"], 1, sweet=1.0)
    k = c.get("/api/kombucha").get_json()["kombucha"]
    assert k["alive"] and k["dies_in"] is not None and k["dies_in"] > 20 * 3600


def test_daily_bonus_counts_answers(qa):
    c = qa["answerer_c"]
    r = c.post("/api/kombucha/daily", json={}).get_json()
    assert r["kombucha"]["xp"] == 18   # 10 + 8 за один ответ
    assert c.post("/api/kombucha/daily", json={}).status_code == 429


def test_stages_and_top(app, make_user):
    assert kb.stage_for(0)["title"] == "Спора"
    assert kb.stage_for(2500)["title"] == "Легенда трёхлитровой банки" and kb.stage_for(2500)["next_xp"] is None
    c, _ = make_user()
    c.post("/api/kombucha/pet", json={})
    top = app.test_client().get("/api/kombucha/top").get_json()["items"]
    assert len(top) == 1 and top[0]["xp"] == 2


def test_guest(app):
    cl = app.test_client()
    assert cl.get("/api/kombucha").status_code == 401
    assert cl.get("/kombucha").status_code == 200
    html = cl.get("/").get_data(as_text=True)
    assert 'href="/debates"' in html and 'href="/kombucha"' in html
