"""Мини-игры гриба: чистый подсчёт + защита от накрутки через API."""
import pytest

from app.errors import ApiError
from app.services import minigames as mg


def test_pour_scoring():
    g = mg.gen_pour(7)
    assert mg.gen_pour(7) == g and len(g["rounds"]) == mg.POUR_ROUNDS
    assert g["rounds"][0]["mods"] == ["shake"] and len(g["rounds"][-1]["mods"]) == 4
    # идеальные наливы: перебором ищем момент, когда итог (с пеной) совпадает с ездящей меткой
    def perfect_ms(rd):
        return min(range(0, 8000, 2), key=lambda ms: 9 if mg.pour_level(rd, ms) >= 1 else abs(mg.pour_final(rd, ms) - mg.pour_target(rd, ms)))
    assert mg.score_pour(g, [perfect_ms(rd) for rd in g["rounds"]])["accuracy"] > 0.97
    n = mg.POUR_ROUNDS
    spill = mg.score_pour(g, [20000] * n)
    assert spill["accuracy"] == 0 and all(r["spilled"] for r in spill["rounds"])
    assert mg.score_pour(g, [0] * n)["accuracy"] == 0
    with pytest.raises(ApiError):
        mg.score_pour(g, [100])


def test_pour_is_hard():
    """Налив «по старинке» — без учёта тряски и пены — больше не даёт высокий балл."""
    accs = []
    for seed in range(40):
        g = mg.gen_pour(seed)
        holds = []
        for rd in g["rounds"]:
            holds.append(min(range(0, 8000, 5), key=lambda ms: abs(mg.pour_level(rd, ms) - rd["target"])))
        accs.append(mg.score_pour(g, holds)["accuracy"])
    assert sum(accs) / len(accs) < 0.6


def test_sugar_scoring():
    g = mg.gen_sugar(3)
    sugar = [it for it in g["items"] if it["kind"] == "sugar"]
    bad = [it for it in g["items"] if it["kind"] != "sugar"]
    ok = [{"id": it["id"], "t": it["t"] + 500} for it in sugar]
    assert mg.score_sugar(g, ok)["accuracy"] == 1.0
    assert mg.score_sugar(g, ok + [{"id": it["id"], "t": it["t"] + 100} for it in bad])["accuracy"] == 0
    # тап по предмету, которого ещё нет на экране (или уже улетел), — не считается
    ghost = [{"id": it["id"], "t": it["t"] - 1000} for it in sugar] + [{"id": it["id"], "t": it["t"] + it["fall"] + 500} for it in sugar]
    assert mg.score_sugar(g, ghost)["caught"] == 0
    assert mg.score_sugar(g, ok + ok)["caught"] == len(sugar)                  # двойной тап — один раз


def test_flies_scoring():
    g = mg.gen_flies(5)
    all_hit = [{"id": f["id"], "t": f["t"] + f["dur"] // 2} for f in g["flies"]]
    r = mg.score_flies(g, all_hit)
    assert r["accuracy"] == 1.0 and r["landed"] == 0 and r["min_ms"] == g["length"]
    none = mg.score_flies(g, [])
    assert none["swatted"] == 0 and none["landed"] == 3
    first3 = sorted(g["flies"], key=lambda f: f["t"] + f["dur"])[:3]
    assert none["min_ms"] == first3[-1]["t"] + first3[-1]["dur"]                # игра кончилась на третьей посадке
    late = [{"id": f["id"], "t": f["t"] + f["dur"] + 500} for f in g["flies"]]  # тапы после посадки не спасают
    assert mg.score_flies(g, late)["swatted"] == 0


def _ff(monkeypatch, ms):
    real = mg._now_ms
    monkeypatch.setattr(mg, "_now_ms", lambda: real() + ms)


def test_memory_flow(make_user, monkeypatch):
    c, _ = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    g = c.post(f"/api/kombucha/{kid}/game/memory/start", json={}).get_json()
    assert len(g["seq"]) == 1 and g["total"] == mg.MEMORY_LEN
    # мгновенный повтор — «слишком быстро»
    r = c.post(f"/api/kombucha/{kid}/game/memory/step", json={"token": g["token"], "input": g["seq"]})
    assert r.status_code == 400
    seq, off = g["seq"], 0
    for _ in range(3):                                                          # три верных шага
        off += 10_000; _ff(monkeypatch, off)
        r = c.post(f"/api/kombucha/{kid}/game/memory/step", json={"token": g["token"], "input": seq}).get_json()
        assert r["ok"] and not r["done"] and r["seq"][:-1] == seq
        seq = r["seq"]
    off += 10_000; _ff(monkeypatch, off)
    wrong = seq[:-1] + [(seq[-1] + 1) % 4]
    r = c.post(f"/api/kombucha/{kid}/game/memory/step", json={"token": g["token"], "input": wrong}).get_json()
    assert r["done"] and not r["ok"] and r["reached"] == 3
    # клиент не может «приписать» себе больше: итог хранит сервер
    fin = c.post(f"/api/kombucha/{kid}/game/memory/finish", json={"token": g["token"], "reached": 12, "won": True}).get_json()
    assert fin["result"]["reached"] == 3 and fin["result"]["accuracy"] == round(3 / 12, 3)
    # играть можно сразу снова, но это тренировка — без награды
    g2 = c.post(f"/api/kombucha/{kid}/game/memory/start", json={})
    assert g2.status_code == 200
    g2 = g2.get_json(); off += 10_000; _ff(monkeypatch, off)
    c.post(f"/api/kombucha/{kid}/game/memory/step", json={"token": g2["token"], "input": [(g2["seq"][0] + 1) % 4]})
    p = c.post(f"/api/kombucha/{kid}/game/memory/finish", json={"token": g2["token"]}).get_json()["result"]
    assert p["practice"] and p["reward_in"] > 0 and p["wood"] == 0 and p["xp"] == 0 and p["happy"] == 0


def test_games_api_guards(make_user, monkeypatch):
    c, _ = make_user()
    c2, _ = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    kid2 = c2.get("/api/kombucha").get_json()["items"][0]["id"]
    assert len(c.get("/api/kombucha/games").get_json()["items"]) == 5
    g = c.post(f"/api/kombucha/{kid}/game/sugar/start", json={}).get_json()
    sugar = [{"id": it["id"], "t": it["t"] + 260 + (it["id"] * 37) % 120} for it in g["items"] if it["kind"] == "sugar"]
    # слишком рано
    r = c.post(f"/api/kombucha/{kid}/game/sugar/finish", json={"token": g["token"], "taps": sugar})
    assert r.status_code == 400
    g = c.post(f"/api/kombucha/{kid}/game/sugar/start", json={}).get_json()
    sugar = [{"id": it["id"], "t": it["t"] + 260 + (it["id"] * 37) % 120} for it in g["items"] if it["kind"] == "sugar"]
    _ff(monkeypatch, g["length"] + 100)
    # чужой токен — 403, и чужую игру он не сжигает
    assert c2.post(f"/api/kombucha/{kid2}/game/sugar/finish", json={"token": g["token"], "taps": []}).status_code == 403
    res = c.post(f"/api/kombucha/{kid}/game/sugar/finish", json={"token": g["token"], "taps": sugar}).get_json()
    R = res["result"]
    assert R["accuracy"] == 1.0 and R["wood"] == 8 and R["boost"] == 15 and R["stat"] == "sweet"
    assert R["xp"] == 5 and R["xp_mult"] == 0.5                                 # игра догнала сахар до 85 — уже вне коридора
    assert res["kombucha"]["stats"]["sweet"] <= 90                              # игрой в сахарную кому не загнать
    assert c.post(f"/api/kombucha/{kid}/game/sugar/finish", json={"token": g["token"], "taps": sugar}).status_code == 400
    assert c.post(f"/api/kombucha/{kid}/game/nope/start", json={}).status_code == 404


def test_game_xp_halved_outside_corridor(make_user, edit_kombucha, monkeypatch):
    c, _ = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    assert c.get("/api/kombucha").get_json()["items"][0]["corridor"]["ok"]
    edit_kombucha(kid, clean=10.0)                       # грязная банка — вне коридора
    g = c.post(f"/api/kombucha/{kid}/game/sugar/start", json={}).get_json()
    taps = [{"id": it["id"], "t": it["t"] + 260 + (it["id"] * 37) % 120} for it in g["items"] if it["kind"] == "sugar"]
    _ff(monkeypatch, g["length"] + 100)
    R = c.post(f"/api/kombucha/{kid}/game/sugar/finish", json={"token": g["token"], "taps": taps}).get_json()["result"]
    assert R["accuracy"] == 1.0 and R["xp"] == 5 and R["xp_mult"] == 0.5         # 10 XP × 0.5


def test_autoclicker_gets_no_reward(app, make_user, monkeypatch):
    from app.services import antibot, antispam
    c, u = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    for i in range(3):
        g = c.post(f"/api/kombucha/{kid}/game/sugar/start", json={}).get_json()
        bot = [{"id": it["id"], "t": it["t"] + 40} for it in g["items"] if it["kind"] == "sugar"]   # реакция 40 мс
        _ff(monkeypatch, g["length"] + 100 + i)
        R = c.post(f"/api/kombucha/{kid}/game/sugar/finish", json={"token": g["token"], "taps": bot}).get_json()["result"]
        assert R["suspect"] == "fast_reactions" and R["accuracy"] == 0 and R["wood"] == 0 and R["bot_flags"] == i + 1
        from app.services import minigames as mg
        from app.extensions import get_redis
        with app.test_request_context():
            get_redis().delete(mg._cd_key(kid, "sugar"))
    # 3 флага — следующая игра только после капчи
    r = c.post(f"/api/kombucha/{kid}/game/flies/start", json={})
    assert r.status_code == 403 and r.get_json()["error"] == "captcha_required"
    users = make_user("admin")[0].get(f"/mod/users?q={u['username']}").get_json()["items"]
    assert users[0]["bot_flags"] == 3


def test_antibot_checks():
    from app.services import antibot as ab
    human = [230, 310, 275, 198, 402, 260, 288]
    assert ab.check_reactions(human) is None
    assert ab.check_reactions([300] * 8) == "robotic_timing"
    assert ab.check_reactions([60, 70, 80, 300, 90, 65]) == "fast_reactions"
    assert ab.check_reactions([300, 310]) is None                   # мало данных — не судим
    assert ab.check_offsets([0, 1, -1, 0, 1, 0, 0]) == "robotic_rhythm"
    assert ab.check_offsets([12, -30, 25, -8, 40, 3, -19]) is None
    assert ab.check_intervals([0, 500, 1000, 1500, 2000, 2500, 3000, 3500]) == "even_intervals"
    assert ab.check_client({"synthetic": 4}) == "synthetic_events" and ab.check_client({"synthetic": 0}) is None


def test_synthetic_events_flagged(make_user, monkeypatch):
    c, _ = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    g = c.post(f"/api/kombucha/{kid}/game/sugar/start", json={}).get_json()
    taps = [{"id": it["id"], "t": it["t"] + 260 + (it["id"] * 37) % 120} for it in g["items"] if it["kind"] == "sugar"]
    _ff(monkeypatch, g["length"] + 100)
    R = c.post(f"/api/kombucha/{kid}/game/sugar/finish", json={"token": g["token"], "taps": taps, "meta": {"synthetic": 12}}).get_json()["result"]
    assert R["suspect"] == "synthetic_events" and R["wood"] == 0
