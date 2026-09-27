"""Номера мутаций, заморозка, полка, рынок, обмен, стена и достижения гриба."""
from tests.test_kombucha import _db, _first, _give_wood, _state

from app.models import Kombucha


def _freeze(c, kid):
    r = c.post(f"/api/kombucha/{kid}/freeze", json={})
    assert r.status_code == 200, r.json
    return r.get_json()


def _badges(c, username):
    return {b["code"] for b in c.get(f"/api/users/{username}").get_json()["badges"]}


# ---------------------------------------------------------------- номера экземпляров
def test_mutation_serials_are_global(app, make_user):
    from app.services import kombucha as kb

    async def fn(s):
        out = []
        for uid in ids:
            k = await s.scalar(__import__("sqlalchemy").select(Kombucha).where(Kombucha.user_id == uid))
            out.append(await kb.add_mutation(s, k, kb.MUT_BY_CODE["golden"], kb.now()))
        return out
    ids = []
    for _ in range(3):
        c, u = make_user()
        _first(c)
        ids.append(u["id"])
    res = _db(app, fn)
    serials = [r["serial"] for r in res]
    assert serials == sorted(serials) and len(set(serials)) == 3 and serials[1] == serials[0] + 1


# ---------------------------------------------------------------- заморозка
def test_freeze_stops_decay_and_frees_jar(app, make_user):
    c, u = make_user()
    kid = _first(c)["id"]
    r = _freeze(c, kid)
    assert r["kombucha"]["frozen"] and r["jars"]["free"] == 1
    assert c.post(f"/api/kombucha/{kid}/pet", json={}).status_code == 409
    # 3 дня в морозилке — статы не падают, не умирает
    async def age(s):
        k = await s.get(Kombucha, kid)
        k.frozen_at -= __import__("datetime").timedelta(days=3)
        k.updated_at -= __import__("datetime").timedelta(days=3)
    _db(app, age)
    k = _first(c)
    assert k["alive"] and k["stats"]["clean"] > 50
    # замороженный стоит на полке профиля
    shelf = c.get(f"/api/users/{u['username']}/shelf").get_json()["items"]
    assert [x["id"] for x in shelf] == [kid]
    assert "kb_freeze" in _badges(c, u["username"])
    # можно посадить новый гриб, тогда разморозить нельзя — нет банки
    assert c.post("/api/kombucha/plant", json={}).status_code == 201
    assert c.post(f"/api/kombucha/{kid}/unfreeze", json={}).get_json()["error"] == "no_free_jar"
    _give_wood(app, u["id"], 300)
    assert c.post("/api/shop/jar", json={}).status_code == 200
    r = c.post(f"/api/kombucha/{kid}/unfreeze", json={}).get_json()
    assert not r["kombucha"]["frozen"] and r["kombucha"]["alive"] and r["kombucha"]["stats"]["clean"] > 50


# ---------------------------------------------------------------- рынок
def test_market_sell_and_buy(app, make_user):
    cs, seller = make_user()
    cb, buyer = make_user()
    kid = _first(cs)["id"]
    # живой незамороженный — нельзя
    assert cs.post(f"/api/kombucha/{kid}/list", json={"price": 100}).status_code == 409
    _freeze(cs, kid)
    assert cs.post(f"/api/kombucha/{kid}/list", json={"price": 5}).status_code == 400
    assert cs.post(f"/api/kombucha/{kid}/list", json={"price": 100}).status_code == 200
    assert cs.post(f"/api/kombucha/{kid}/unfreeze", json={}).get_json()["error"] == "kombucha_listed"
    items = cb.get("/api/market").get_json()["items"]
    assert any(i["id"] == kid and i["owner"] == seller["username"] and i["price"] == 100 for i in items)
    assert cs.post(f"/api/market/{kid}/buy", json={}).get_json()["error"] == "own_kombucha"
    w_seller = _state(cs)["wood"]
    assert cb.post(f"/api/market/{kid}/buy", json={}).get_json()["error"] == "not_enough_wood"
    _give_wood(app, buyer["id"], 500)
    w_buyer = _state(cb)["wood"]
    assert cb.post(f"/api/market/{kid}/buy", json={"price": 99}).get_json()["error"] == "price_changed"
    r = cb.post(f"/api/market/{kid}/buy", json={"price": 100})
    assert r.status_code == 200, r.json
    assert r.get_json()["wood"] == w_buyer - 100
    assert _state(cs)["wood"] == w_seller + 95           # 5% комиссии сгорает
    mine = [k["id"] for k in _state(cb)["items"]]
    assert kid in mine and kid not in [k["id"] for k in _state(cs)["items"]]
    assert all(i["id"] != kid for i in cb.get("/api/market").get_json()["items"])
    assert "kb_sale" in _badges(cs, seller["username"]) and "kb_buy" in _badges(cb, buyer["username"])
    kinds = [n["kind"] for n in cs.get("/api/notifications").get_json()["items"]]
    assert "sale" in kinds


# ---------------------------------------------------------------- обмен
def test_trade_swap_and_gift(make_user):
    c1, u1 = make_user()
    c2, u2 = make_user()
    k1, k2 = _first(c1)["id"], _first(c2)["id"]
    r = c1.post("/api/trades", json={"to_username": u2["username"], "give_id": k1, "want_id": k2})
    assert r.get_json()["error"] == "kombucha_not_frozen"
    _freeze(c1, k1)
    _freeze(c2, k2)
    assert c1.post("/api/trades", json={"to_username": u1["username"], "give_id": k1}).status_code == 409
    t = c1.post("/api/trades", json={"to_username": u2["username"], "give_id": k1, "want_id": k2}).get_json()["trade"]
    inc = c2.get("/api/trades").get_json()["incoming"]
    assert inc[0]["id"] == t["id"] and inc[0]["give"]["id"] == k1 and inc[0]["want"]["id"] == k2
    assert c1.post(f"/api/trades/{t['id']}/accept", json={}).status_code == 403
    assert c2.post(f"/api/trades/{t['id']}/accept", json={}).status_code == 200
    assert [k["id"] for k in _state(c1)["items"]] == [k2]
    assert [k["id"] for k in _state(c2)["items"]] == [k1]
    assert c2.post(f"/api/trades/{t['id']}/accept", json={}).get_json()["error"] == "trade_closed"
    assert "kb_trade" in _badges(c1, u1["username"])
    # подарок (want_id = null), затем отмена
    g = c1.post("/api/trades", json={"to_username": u2["username"], "give_id": k2}).get_json()["trade"]
    assert c1.post(f"/api/trades/{g['id']}/cancel", json={}).get_json()["trade"]["status"] == "cancelled"
    g = c1.post("/api/trades", json={"to_username": u2["username"], "give_id": k2}).get_json()["trade"]
    assert c2.post(f"/api/trades/{g['id']}/accept", json={}).status_code == 200
    assert _state(c1)["items"] == [] or all(k["id"] != k2 for k in _state(c1)["items"])


# ---------------------------------------------------------------- стена
def test_wall(make_user):
    co, owner = make_user()
    ca, author = make_user()
    cm, _ = make_user("moderator")
    cx, _ = make_user()
    url = f"/api/users/{owner['username']}/wall"
    r = ca.post(url, json={"body": "Привет, **схематоз**!"})
    assert r.status_code == 201 and "<strong>" in r.get_json()["post"]["body_html"]
    assert ca.post(url, json={"body": "x" * 501}).status_code == 400
    items = cx.get(url).get_json()["items"]
    assert items[0]["author"]["username"] == author["username"] and not items[0]["can_delete"]
    pid = items[0]["id"]
    assert "wall" in [n["kind"] for n in co.get("/api/notifications").get_json()["items"]]
    assert cx.delete(f"/api/wall/{pid}").status_code == 403
    assert co.delete(f"/api/wall/{pid}").status_code == 200        # хозяин стены
    pid2 = ca.post(url, json={"body": "ещё"}).get_json()["post"]["id"]
    assert cm.delete(f"/api/wall/{pid2}").status_code == 200       # модератор
    assert cx.get(url).get_json()["items"] == []
    # хозяин закрыл стену
    assert co.patch("/api/me/profile", json={"wall_closed": True}).status_code == 200
    assert ca.post(url, json={"body": "можно?"}).get_json()["error"] == "wall_closed"
    assert co.post(url, json={"body": "мне можно"}).status_code == 201


def test_achievements_catalog_in_badges():
    from app.services.gamification import BADGES
    for code in ("kb_first", "kb_first_mut", "kb_mut120", "kb_legendary", "kb_trade", "kb_sale", "kb_rich"):
        assert code in BADGES


def test_first_kombucha_badge(make_user):
    c, u = make_user()
    _first(c)
    assert "kb_first" in _badges(c, u["username"])


def test_gift_with_message_and_provenance(make_user):
    c1, u1 = make_user()
    c2, u2 = make_user()
    k1 = _first(c1)["id"]
    _freeze(c1, k1)
    t = c1.post("/api/trades", json={"to_username": u2["username"], "give_id": k1, "message": "С днём варенья 🎂"}).get_json()["trade"]
    inc = c2.get("/api/trades").get_json()["incoming"][0]
    assert inc["gift"] and inc["message"] == "С днём варенья 🎂"
    assert c2.post(f"/api/trades/{t['id']}/accept", json={}).status_code == 200
    card = c1.get(f"/api/kombucha/{k1}/card").get_json()["kombucha"]
    assert card["owner"] == u2["username"]
    assert [o["username"] for o in card["owners"]] == [u1["username"], u2["username"]]
    assert [o["how"] for o in card["owners"]] == ["grown", "gift"]
    assert "kb_gift" in _badges(c1, u1["username"])
