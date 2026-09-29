"""Мини-игра «Медитация гриба»: подсчёт попаданий и защита от накрутки."""
import pytest

from app.services import meditation as med


def test_score_perfect_offsets_and_spam():
    tr = med.make_track(42)
    beats = tr["beats"]
    assert len(beats) == med.BEATS and beats == sorted(beats) and tr["length"] > beats[-1]
    assert med.make_track(42) == tr                                  # детерминирован по seed
    assert med.score(beats, beats)["accuracy"] == 1.0
    lag = med.score(beats, [b + 120 for b in beats])                 # стабильная задержка экрана — компенсируется
    assert lag["accuracy"] == 1.0 and lag["shift_ms"] == 120
    assert med.score(beats, [])["accuracy"] == 0
    spam = list(range(0, tr["length"], 40))                          # долбим по экрану без ритма
    assert med.score(beats, spam)["accuracy"] < 0.3
    half = med.score(beats, beats[::2])
    assert 0.4 < half["accuracy"] < 0.6 and half["miss"] == len(beats) // 2


def _fast_forward(monkeypatch, ms):
    real = med._now_ms
    monkeypatch.setattr(med, "_now_ms", lambda: real() + ms)


def test_meditation_flow(make_user, monkeypatch):
    c, _ = make_user()
    st = c.get("/api/kombucha").get_json()
    kid = st["items"][0]["id"]
    happy0, wood0 = st["items"][0]["stats"]["happy"], st["wood"]
    t = c.post(f"/api/kombucha/{kid}/meditate/start", json={}).get_json()
    assert t["token"] and len(t["beats"]) == med.BEATS
    # мгновенно «сыграть» нельзя
    r = c.post(f"/api/kombucha/{kid}/meditate/finish", json={"token": t["token"], "taps": t["beats"]})
    assert r.status_code == 400 and r.get_json()["error"] == "med_too_fast"
    # новая попытка (сессия сгорела) — кулдауна ещё нет, т.к. награды не было
    t = c.post(f"/api/kombucha/{kid}/meditate/start", json={}).get_json()
    _fast_forward(monkeypatch, t["length"] + 100)
    monkeypatch.setattr(med.rng, "random", lambda: 0.0)              # гарантируем мутацию при 100%
    r = c.post(f"/api/kombucha/{kid}/meditate/finish", json={"token": t["token"], "taps": t["beats"]}).get_json()
    res = r["result"]
    assert res["accuracy"] == 1.0 and res["wood"] == 10 and res["happy"] == 25 and res["mutation"] and res["mut_why"] == "got"
    assert r["kombucha"]["stats"]["happy"] >= min(100, happy0)
    assert r["wood_balance"] >= wood0 + 10
    # повтор той же сессии — нельзя
    again = c.post(f"/api/kombucha/{kid}/meditate/finish", json={"token": t["token"], "taps": t["beats"]})
    assert again.status_code == 400
    # кулдаун
    cd = c.post(f"/api/kombucha/{kid}/meditate/start", json={})
    assert cd.status_code == 429 and cd.get_json()["error"] == "kb_cooldown"


def test_meditation_foreign_and_limits(make_user, monkeypatch):
    c1, _ = make_user()
    c2, _ = make_user()
    k1 = c1.get("/api/kombucha").get_json()["items"][0]["id"]
    k2 = c2.get("/api/kombucha").get_json()["items"][0]["id"]
    assert c2.post(f"/api/kombucha/{k1}/meditate/start", json={}).status_code == 404   # чужой гриб
    t = c1.post(f"/api/kombucha/{k1}/meditate/start", json={}).get_json()
    _fast_forward(monkeypatch, t["length"] + 100)
    # чужой токен к своему грибу
    assert c2.post(f"/api/kombucha/{k2}/meditate/finish", json={"token": t["token"], "taps": []}).status_code == 403
    # слишком много тапов
    t = c1.post(f"/api/kombucha/{k1}/meditate/start", json={}).get_json()
    bad = c1.post(f"/api/kombucha/{k1}/meditate/finish", json={"token": t["token"], "taps": list(range(500))})
    assert bad.status_code == 400
