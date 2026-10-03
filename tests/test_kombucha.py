"""Мини-игра «Чайный гриб», мутации, отростки, банки и «Деревянные» ($₽)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Kombucha
from app.services import kombucha as kb


def _db(app, fn):
    from app.db import session_scope

    async def run():
        async with session_scope() as s:
            return await fn(s)
    with app.app_context():
        return asyncio.run(run())


def _edit(app, kid, hours=0, **fields):
    """Отмотать время гриба назад на `hours` и/или поменять поля."""
    async def fn(s):
        k = await s.get(Kombucha, kid)
        k.updated_at -= timedelta(hours=hours)
        k.born_at -= timedelta(hours=hours)
        k.cooldowns = {}
        for key, v in fields.items():
            setattr(k, key, v)
    _db(app, fn)


def _give_wood(app, user_id, amount):
    from app.services import wood

    async def fn(s):
        await wood.earn(s, user_id, "mutation", f"test{amount}", amount)
    _db(app, fn)


def _state(c):
    return c.get("/api/kombucha").get_json()


def _first(c):
    return _state(c)["items"][0]


@pytest.fixture()
def no_mutations(monkeypatch):
    monkeypatch.setattr(kb.rng, "random", lambda: 0.999)


# ---------------------------------------------------------------- базовая игра
def test_create_and_actions(make_user, no_mutations):
    c, _ = make_user()
    st = _state(c)
    k = st["items"][0]
    assert k["alive"] and k["stage"]["title"] == "Спора" and st["jars"] == {"jars": 1, "used": 1, "free": 0, "max": 5}
    assert len(st["catalog"]) == 240
    r = c.post(f"/api/kombucha/{k['id']}/tea", json={})
    assert r.status_code == 200 and r.get_json()["kombucha"]["stats"]["tea"] == 95
    again = c.post(f"/api/kombucha/{k['id']}/tea", json={})
    assert again.status_code == 429 and again.get_json()["retry_after"] > 3 * 3600
    assert c.post(f"/api/kombucha/{k['id']}/hack", json={}).status_code == 404


def test_cannot_touch_foreign_kombucha(make_user):
    c1, _ = make_user()
    c2, _ = make_user()
    kid = _first(c1)["id"]
    assert c2.post(f"/api/kombucha/{kid}/tea", json={}).status_code == 404
    assert c2.patch(f"/api/kombucha/{kid}", json={"name": "Украл"}).status_code == 404


def test_unique_names(make_user):
    c1, _ = make_user()
    c2, _ = make_user()
    k1, k2 = _first(c1), _first(c2)
    assert k1["name"].lower() != k2["name"].lower()
    assert c1.patch(f"/api/kombucha/{k1['id']}", json={"name": "Бульбозавр"}).status_code == 200
    r = c2.patch(f"/api/kombucha/{k2['id']}", json={"name": "бульбозАВР"})
    assert r.status_code == 409 and r.get_json()["error"] == "name_taken"
    # своё же имя можно «переименовать» в него же
    assert c1.patch(f"/api/kombucha/{k1['id']}", json={"name": "Бульбозавр"}).status_code == 200
    assert c1.patch(f"/api/kombucha/{k1['id']}", json={"name": "<script>"}).status_code == 400


def test_decay_is_every_12_hours(app, make_user, no_mutations):
    c, _ = make_user()
    k = _first(c)
    _edit(app, k["id"], hours=11)
    k2 = _first(c)
    assert k2["stats"] == k["stats"]                           # 11 ч — ещё ничего не упало
    assert 0 < k2["next_drop_in"] <= 3600
    _edit(app, k["id"], hours=1)
    k3 = _first(c)
    assert k3["stats"]["sweet"] == k["stats"]["sweet"] - 20   # 12 ч — одна ступенька
    assert k3["stats"]["tea"] == k["stats"]["tea"] - 15
    assert k3["next_drop_in"] > 11 * 3600
    # уход не сдвигает таймер ступенек
    c.post(f"/api/kombucha/{k['id']}/pet", json={})
    assert _first(c)["next_drop_in"] > 11 * 3600


def test_oversugar_makes_it_sticky(app, make_user, no_mutations):
    c, _ = make_user()
    kid = _first(c)["id"]
    _edit(app, kid, sweet=95.0)
    r = c.post(f"/api/kombucha/{kid}/sugar", json={}).get_json()
    assert "слипся" in r["message"] and r["kombucha"]["mood"] == "sticky"


def test_death_restart_revive_discard(app, make_user, no_mutations):
    c, u = make_user()
    kid = _first(c)["id"]
    _edit(app, kid, hours=24 * 5)
    k = _first(c)
    assert not k["alive"] and k["mood"] == "dead"
    assert c.post(f"/api/kombucha/{kid}/tea", json={}).status_code == 409
    # реанимация стоит денег
    r = c.post(f"/api/kombucha/{kid}/revive", json={})
    assert r.status_code == 402 and r.get_json()["error"] == "not_enough_wood"
    _give_wood(app, u["id"], 500)
    bal = _state(c)["wood"]
    r = c.post(f"/api/kombucha/{kid}/revive", json={}).get_json()
    assert r["kombucha"]["alive"] and r["wood"] == bal - 150
    # снова убиваем → перезаводим
    _edit(app, kid, hours=24 * 5)
    k = c.post(f"/api/kombucha/{kid}/restart", json={"name": "Гриша Второй"}).get_json()["kombucha"]
    assert k["alive"] and k["generation"] == 2 and k["xp"] == 0 and k["name"] == "Гриша Второй"
    assert c.delete(f"/api/kombucha/{kid}").status_code == 409     # живой — не выбросить
    _edit(app, kid, hours=24 * 5)
    assert c.delete(f"/api/kombucha/{kid}").status_code == 200
    assert _state(c)["jars"]["free"] == 1


def test_danger_timer(app, make_user, no_mutations):
    c, _ = make_user()
    kid = _first(c)["id"]
    _edit(app, kid, hours=12, sweet=10.0)
    k = _first(c)
    assert k["alive"] and k["stats"]["sweet"] == 0 and 47 * 3600 < k["dies_in"] <= 48 * 3600   # закиснет через 48 ч


def test_daily_bonus_counts_care(make_user, no_mutations):
    c, _ = make_user()
    kid = _first(c)["id"]
    c.post(f"/api/kombucha/{kid}/pet", json={})
    c.post(f"/api/kombucha/{kid}/clean", json={})
    r = c.post(f"/api/kombucha/{kid}/daily", json={}).get_json()
    assert r["kombucha"]["xp"] == 2 + 12 + 5           # игр не было — только база 5 XP
    wtx = [t for t in c.get("/api/wallet").get_json()["items"] if t["reason"] == "daily_bonus"]
    assert wtx[0]["delta"] == 5 + 2                     # 5 + по 1 $₽ за каждый уход за сутки
    assert c.post(f"/api/kombucha/{kid}/daily", json={}).status_code == 429


# ---------------------------------------------------------------- мутации
def test_120_mutations_20_per_stage():
    from collections import Counter
    assert len(kb.MUTATIONS) == 240 and len(kb.MUT_BY_CODE) == 240
    assert Counter(m.stage for m in kb.MUTATIONS) == {i: 40 for i in range(1, 7)}
    assert {m.rarity for m in kb.MUTATIONS} == set(kb.RARITY_ORDER)
    for old in ("sparkle", "night", "sweet_tooth", "bubbly", "phoenix"):   # старые коды живы
        assert old in kb.MUT_BY_CODE


def test_mutation_is_saved_and_rewarded(app, make_user, monkeypatch):
    c, u = make_user()
    kid = _first(c)["id"]
    monkeypatch.setattr(kb.rng, "random", lambda: 0.0)       # всё, что может выпасть, — выпадает
    wood0 = _state(c)["wood"]
    r = c.post(f"/api/kombucha/{kid}/pet", json={}).get_json()
    code = r["mutation"]["code"]
    assert r["mutation"]["first_time"] and r["mutation"]["serial"] >= 1
    assert r["kombucha"]["mutations"][0]["code"] == code and r["kombucha"]["mutations"][0]["serial"]
    st = _state(c)
    assert st["wood"] >= wood0 + 15 + 1
    assert [x["code"] for x in st["codex"]] == [code]
    # мутация остаётся после смерти и перезапуска в коллекции
    _edit(app, kid, hours=24 * 5)
    c.post(f"/api/kombucha/{kid}/restart", json={})
    st = _state(c)
    assert st["items"][0]["mutations"] == [] and [x["code"] for x in st["codex"]] == [code]


def test_mutation_conditions():
    M = kb.MUT_BY_CODE
    k = Kombucha(xp=0, sweet=85.0, tea=10.0, clean=90.0, happy=50.0, mutations=[], pet_count=0, generation=1)
    assert M["sweet_tooth"].check(kb.Ctx(action="sugar", k=k, hour=14))
    assert not M["sweet_tooth"].check(kb.Ctx(action="tea", k=k, hour=14))
    assert M["night"].check(kb.Ctx(action="tea", k=k, hour=3))
    assert not M["night"].check(kb.Ctx(action="tea", k=k, hour=14))
    assert M["bubbly"].check(kb.Ctx(action="tea", k=k, hour=14))
    assert not M["phoenix"].check(kb.Ctx(action="pet", k=k, hour=14))
    k.generation = 2
    assert M["phoenix"].check(kb.Ctx(action="pet", k=k, hour=14))
    # стадия ограничивает: споре не выпадет мутация 2+ стадии
    orig = kb.rng.random
    kb.rng.random = lambda: 0.0
    try:
        for _ in range(30):
            m = kb.roll_mutation(kb.Ctx(action="pet", k=k, hour=14))
            assert m is None or m.stage == 1
        # уже имеющиеся не повторяются
        k.mutations = [{"code": m.code} for m in kb.MUTATIONS if m.stage == 1]
        assert kb.roll_mutation(kb.Ctx(action="pet", k=k, hour=14)) is None
    finally:
        kb.rng.random = orig


# ---------------------------------------------------------------- банки и отростки
def test_buy_jar_and_plant(app, make_user, no_mutations):
    c, u = make_user()
    _state(c)
    assert c.post("/api/kombucha/plant", json={}).get_json()["error"] == "no_free_jar"
    assert c.post("/api/shop/jar", json={}).status_code == 402
    _give_wood(app, u["id"], 1000)
    r = c.post("/api/shop/jar", json={}).get_json()
    assert r["jars"]["jars"] == 2 and r["jars"]["free"] == 1
    k2 = c.post("/api/kombucha/plant", json={"name": "Второй Бульк"}).get_json()["kombucha"]
    assert k2["name"] == "Второй Бульк"
    assert len(_state(c)["items"]) == 2
    hist = c.get("/api/wallet").get_json()
    assert any(t["reason"] == "buy_jar" and t["delta"] == -300 for t in hist["items"])


def test_sprout_after_week_of_care_on_last_stage(app, make_user, no_mutations):
    c, u = make_user()
    kid = _first(c)["id"]
    _edit(app, kid, xp=1600, care_days=2, mutations=[{"code": "golden", "at": "x"}])
    r = c.post(f"/api/kombucha/{kid}/pet", json={}).get_json()
    assert r["sprout"] == {"planted": False}          # 3-й день ухода, но банки нет — отросток ждёт
    assert r["kombucha"]["sprout_pending"]
    _give_wood(app, u["id"], 1000)
    res = c.post("/api/shop/jar", json={}).get_json()
    assert len(res["sprouts"]) == 1                   # купил банку — отросток сел сам
    items = _state(c)["items"]
    child = next(k for k in items if k["id"] != kid)
    assert child["is_sprout"] and child["mutations"][0]["code"] == "golden" and child["mutations"][0]["inherited"]
    assert not next(k for k in items if k["id"] == kid)["sprout_pending"]


def test_sprout_every_week(app, make_user, no_mutations):
    from datetime import timedelta as td
    c, u = make_user()
    kid = _first(c)["id"]
    _give_wood(app, u["id"], 1000)
    c.post("/api/shop/jar", json={})
    c.post("/api/shop/jar", json={})
    _edit(app, kid, xp=1600, care_days=2)
    r = c.post(f"/api/kombucha/{kid}/pet", json={}).get_json()
    assert r["sprout"]["planted"] and r["kombucha"]["sprout_progress"]["count"] == 1
    assert r["kombucha"]["sprout_progress"]["next_in"] > 2 * 86400
    # неделя ещё не прошла — даже с 7 днями ухода не делится
    _edit(app, kid, care_days=2, last_care_day=None)
    r = c.post(f"/api/kombucha/{kid}/sugar", json={}).get_json()
    assert r["sprout"] is None

    async def week_ago(s):
        k = await s.get(Kombucha, kid)
        k.last_sprout_at -= td(days=3)
    _db(app, week_ago)
    _edit(app, kid, care_days=2, last_care_day=None)
    r = c.post(f"/api/kombucha/{kid}/tea", json={}).get_json()
    assert r["sprout"]["planted"] and r["kombucha"]["sprout_progress"]["count"] == 2


def test_mold_blocks_growth_and_cure(app, make_user, no_mutations):
    c, u = make_user()
    kid = _first(c)["id"]
    assert c.post(f"/api/kombucha/{kid}/cure", json={}).get_json()["error"] == "not_moldy"
    _edit(app, kid, mold=True)
    k = _first(c)
    assert k["mold"] and k["mood"] == "moldy"
    xp0 = k["xp"]
    r = c.post(f"/api/kombucha/{kid}/tea", json={}).get_json()
    assert r["kombucha"]["xp"] == xp0                    # с плесенью не растёт
    r = c.post(f"/api/kombucha/{kid}/cure", json={}).get_json()
    assert not r["kombucha"]["mold"]
    r = c.post(f"/api/kombucha/{kid}/clean", json={}).get_json()
    assert r["kombucha"]["xp"] > xp0


def test_mold_appears_in_dirty_jar(app, make_user, monkeypatch):
    c, u = make_user()
    kid = _first(c)["id"]
    monkeypatch.setattr(kb.rng, "random", lambda: 0.0)
    _edit(app, kid, hours=12, clean=15.0)
    assert _first(c)["mold"]


def test_talk_and_pet_quotes(make_user, no_mutations):
    from app.services import quotes
    c, _ = make_user()
    kid = _first(c)["id"]
    r = c.post(f"/api/kombucha/{kid}/talk", json={}).get_json()
    q = r["quote"]
    assert q["lines"] and q["book"] and not q["remote"]
    assert any(q["book"] == b for b, _ in quotes.PHILO)
    r = c.post(f"/api/kombucha/{kid}/pet", json={}).get_json()
    assert r["quote"]["lines"][0]["who"] in {w for w, _, _ in quotes.DUBIOUS}
    assert c.post(f"/api/kombucha/{kid}/talk", json={}).status_code == 429


def test_quotes_remote_parser_and_fallback(app, monkeypatch):
    from app.services import quotes
    assert quotes._parse({"quote": "I am a god"}) is None               # английское не берём
    assert quotes._parse({"quoteText": "Терпение и труд всё перетрут", "quoteAuthor": "Пословица "}) == \
        ("Терпение и труд всё перетрут", "Пословица")
    assert quotes._parse([{"q": "Меньше — значит больше", "a": "Кто-то"}]) == ("Меньше — значит больше", "Кто-то")
    assert quotes._parse({"nope": 1}) is None

    class R:
        status_code = 200
        def json(self):
            return {"quoteText": "Удалённая мудрость"}
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    app.config["QUOTES_REMOTE"] = True
    try:
        with app.app_context():
            from app.extensions import get_redis
            get_redis().delete("quotes:test", "quotes:test:backoff")
            q = quotes._remote("test", "https://example.invalid/q", "Неизвестный мудрец")
            assert q["remote"] and q["lines"][0] == {"who": "Неизвестный мудрец", "text": "Удалённая мудрость"}
            # сервис упал — кэш остаётся, а на 10 минут включается пауза
            monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
            from app.extensions import get_redis
            get_redis().delete("quotes:test2")
            assert quotes._remote("test2", "https://example.invalid/q", "X") is None
            assert get_redis().exists("quotes:test2:backoff")
    finally:
        app.config["QUOTES_REMOTE"] = False


# ---------------------------------------------------------------- «Деревянные»
def test_wood_only_from_care_games_and_login(make_user, no_mutations):
    c, _ = make_user()
    me1 = c.get("/api/auth/me").get_json()
    me2 = c.get("/api/auth/me").get_json()
    assert me1["wood_daily"] >= 10 and me2["wood_daily"] == 0 and me2["wood"] == me1["wood"]
    kid = _first(c)["id"]
    c.post(f"/api/kombucha/{kid}/pet", json={})
    reasons = {t["reason"] for t in c.get("/api/wallet").get_json()["items"]}
    assert reasons == {"daily_login", "kombucha_care"}
    from app.services import wood
    assert set(wood.EARN) == {"daily_login", "kombucha_care", "daily_bonus", "mutation", "sprout",
                              "minigame", "meditation", "sale"}


def test_wood_daily_cap(app, make_user):
    from app.services import wood
    c, u = make_user()

    async def fn(s):
        return [await wood.earn(s, u["id"], "kombucha_care", i) for i in range(35)]
    got = _db(app, fn)
    assert sum(got) == 20 and got[-1] == 0


def test_top_and_guest(app, make_user, no_mutations):
    c, _ = make_user()
    kid = _first(c)["id"]
    c.post(f"/api/kombucha/{kid}/pet", json={})
    top = app.test_client().get("/api/kombucha/top").get_json()["items"]
    assert top[0]["kombucha"]["xp"] == 2
    cl = app.test_client()
    assert cl.get("/api/kombucha").status_code == 401
    assert cl.get("/api/wallet").status_code == 401
    assert cl.get("/kombucha").status_code in (301, 302)
    html = cl.get("/").get_data(as_text=True)
    assert 'id="home-top"' in html and 'href="/market"' in html and 'href="/debates"' not in html


def test_all_quotes_are_russian():
    from app.services import quotes
    for who, src, text in quotes.DUBIOUS:
        assert quotes.is_russian(text) and quotes.is_russian(who), text
    for book, lines in quotes.PHILO:
        for who, text in lines:
            assert quotes.is_russian(text) and quotes.is_russian(who), text


def test_bubble_quotes_unless_sugar_coma(app, make_user, no_mutations):
    from app.services import quotes
    c, _ = make_user()
    kid = _first(c)["id"]
    texts = {t for _, _, t in quotes.DUBIOUS}
    for stats in ({}, {"sweet": 10.0}, {"clean": 10.0}):          # доволен, голоден, грязно — всё равно цитата
        _edit(app, kid, **{"sweet": 70.0, "tea": 70.0, "clean": 90.0, "happy": 70.0, **stats})
        ph = _first(c)["phrase"]
        assert ph in texts, ph                                     # от первого лица: только сама фраза
    _edit(app, kid, sweet=99.0)
    k = _first(c)
    assert k["mood"] == "sticky" and k["phrase"] not in texts
    assert k["phrase"] in kb.TALK["sticky"]


def test_sprout_only_on_last_stage(app, make_user, no_mutations):
    c, u = make_user()
    kid = _first(c)["id"]
    _give_wood(app, u["id"], 1000)
    c.post("/api/shop/jar", json={})
    for stage_xp in (0, 80, 250, 550, 1000, 1500):              # все стадии до «Легенды»
        _edit(app, kid, xp=stage_xp, care_days=30, last_care_day=None)
        r = c.post(f"/api/kombucha/{kid}/pet", json={}).get_json()
        assert r["sprout"] is None and not r["kombucha"]["sprout_progress"]["legend"], stage_xp
    _edit(app, kid, xp=1600, care_days=2, last_care_day=None)
    r = c.post(f"/api/kombucha/{kid}/sugar", json={}).get_json()
    assert r["sprout"] and r["sprout"]["planted"]


def test_max_three_mutations_per_stage():
    from types import SimpleNamespace
    from app.services.kombucha_mutations import MUTATIONS, Ctx
    s1 = [m for m in MUTATIONS if m.stage == 1]
    k = SimpleNamespace(xp=0, mutations=[{"code": m.code} for m in s1[:2]], mold=False)
    import pytest as _p
    mp = _p.MonkeyPatch()
    try:
        mp.setattr(kb.rng, "random", lambda: 0.0)                  # любой шанс срабатывает
        from app.services.kombucha_mutations import Mutation
        mp.setattr(Mutation, "check", lambda self, ctx: True)
        ctx = Ctx(action="pet", k=k, hour=12, weekday=1)
        got = kb.roll_mutation(ctx)
        assert got is not None and got.stage == 1                  # третья на стадии 1 ещё можно
        k.mutations.append({"code": got.code})
        assert kb.stage_mut_counts(k) == {1: 3}
        for _ in range(50):
            assert kb.roll_mutation(ctx) is None                   # стадия 1 заполнена
        k.xp = 10 ** 6                                             # Легенда: падают только мутации 6-й стадии
        for _ in range(3):
            m = kb.roll_mutation(ctx)
            assert m.stage == 6
            k.mutations.append({"code": m.code})
        assert kb.roll_mutation(ctx) is None                       # и их тоже не больше 3
    finally:
        mp.undo()


def test_admin_kombucha_debug(make_user, no_mutations):
    from app.services.kombucha_mutations import MUTATIONS
    c, u = make_user()
    kid = _first(c)["id"]
    mc, _ = make_user("moderator")
    assert mc.get(f"/admin/kombucha?user={u['username']}").status_code == 403   # только админ
    assert mc.patch(f"/admin/kombucha/{kid}", json={"stage": 6}).status_code == 403
    ac, _ = make_user("admin")
    d = ac.get(f"/admin/kombucha?user={u['username']}").get_json()
    assert d["items"][0]["id"] == kid and len(d["catalog"]) == 240 and len(d["stages"]) == 6
    k = ac.patch(f"/admin/kombucha/{kid}", json={"stage": 5}).get_json()["kombucha"]
    assert k["stage"]["size"] == 5
    codes = [m.code for m in MUTATIONS if m.stage == 1][:5] + [MUTATIONS[-1].code]   # в обход лимита 3/стадию
    k = ac.patch(f"/admin/kombucha/{kid}", json={"mutations": codes}).get_json()["kombucha"]
    assert sorted(m["code"] for m in k["mutations"]) == sorted(codes) and all(m["serial"] == 0 for m in k["mutations"])
    k = ac.patch(f"/admin/kombucha/{kid}", json={"stats": {"sweet": 99}, "mold": True}).get_json()["kombucha"]
    assert k["stats"]["sweet"] == 99 and k["mold"]
    assert ac.patch(f"/admin/kombucha/{kid}", json={"mutations": ["nope"]}).status_code == 400
    assert ac.patch(f"/admin/kombucha/{kid}", json={"stage": 9}).status_code == 400
    # владелец видит изменения, тиражи не тронуты
    assert len(_first(c)["mutations"]) == 6
    cat = {m["code"]: m for m in _state(c)["catalog"]}
    assert cat[codes[0]]["issued"] == 0



def test_quotes_first_person(app, make_user):
    from app.services import quotes
    with app.app_context():
        for _ in range(60):
            for q in (quotes.dubious(remote=False), quotes.philosophy()):
                sp = quotes.as_speech(q)
                assert sp and not any(w in sp for w in ("Как говорил", "процитировал", "Гриб ")), sp
                assert "intro" not in q
    names = {w for w, _, _ in quotes.DUBIOUS}
    for must in ("Владимир Маяковский", "Бенито Муссолини", "Освальд Мосли"):
        assert must in names
