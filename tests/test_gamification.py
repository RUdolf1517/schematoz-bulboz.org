from datetime import date, datetime, timedelta

from app.services.gamification import iso_week, level_name, next_streak, visible_streak
from app.services.reputation import level_for

D = date(2026, 9, 26)


def test_streak_rules():
    used = "2026-W39"  # 26.09.2026 — это 39-я ISO-неделя: заморозка уже потрачена
    assert next_streak(0, None, D, used) == (1, False)
    assert next_streak(5, D, D, used) == (5, False)                        # второй ответ за день
    assert next_streak(5, D - timedelta(days=1), D, used) == (6, False)    # вчера отвечал
    assert next_streak(5, D - timedelta(days=2), D, used) == (1, False)    # пропуск, заморозки нет
    assert visible_streak(5, D - timedelta(days=1), D, used) == 5
    assert visible_streak(5, D - timedelta(days=2), D, used) == 0


def test_streak_freeze():
    assert iso_week(D) == "2026-W39"
    # пропущен один день, заморозка доступна — стрик продолжается и заморозка тратится
    assert next_streak(5, D - timedelta(days=2), D, None) == (6, True)
    assert next_streak(5, D - timedelta(days=2), D, "2026-W38") == (6, True)
    assert visible_streak(5, D - timedelta(days=2), D, None) == 5
    # два пропущенных дня заморозка не спасает
    assert next_streak(5, D - timedelta(days=3), D, None) == (1, False)
    assert visible_streak(5, D - timedelta(days=3), D, None) == 0


def test_levels():
    assert level_for(0) == 1 and level_for(10) == 2
    assert level_for(10**9) == 50
    assert level_name(1) == "Нуб" and level_name(12) == "Мудрец с подъезда"


def test_badges_for_first_question_answer_and_scheme(qa):
    prof = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json
    assert {b["code"] for b in prof["badges"]} == {"first_answer"}
    assert prof["user"]["streak_days"] == 1
    author = qa["other_c"].get(f"/api/users/{qa['author']['username']}").json
    assert "first_question" in {b["code"] for b in author["badges"]}

    r = qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    assert r.json["author_new_badges"] == ["first_scheme"]
    # передумал и снова +5 — второй раз не выдаётся, схема считается один раз
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": -1})
    r = qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    assert r.json["author_new_badges"] == []
    prof = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json
    assert prof["stats"]["schemes"] == 1
    assert prof["best_answers"][0]["answer_id"] == qa["a"]["id"]


def test_debater_badge_and_debate_votes(make_user):
    c, _ = make_user()
    q = c.post("/api/questions", json={"kind": "debate", "title": "Дота или Лига?",
                                       "side_a": "Дота", "side_b": "Лига"}).json["question"]
    c2, u2 = make_user()
    r = c2.post(f"/api/questions/{q['id']}/answers", json={"body": "Дота", "debate_side": "a"})
    assert "debater" in r.json["new_badges"]
    assert c2.put(f"/api/questions/{q['id']}/debate-vote", json={"side": "a"}).json["a"] == 1
    r = c2.put(f"/api/questions/{q['id']}/debate-vote", json={"side": "b"})  # передумал
    assert (r.json["a"], r.json["b"], r.json["my_side"]) == (0, 1, "b")
    assert c.put(f"/api/questions/{q['id']}/debate-vote", json={"side": "x"}).status_code == 400
    d = c2.get(f"/api/questions/{q['id']}").json["debate_votes"]
    assert d["my_side"] == "b" and d["b_pct"] == 100


def test_debate_vote_rejected_for_normal_question(qa):
    r = qa["other_c"].put(f"/api/questions/{qa['q']['id']}/debate-vote", json={"side": "a"})
    assert r.status_code == 400 and r.json["error"] == "not_a_debate"


def test_share_images(qa):
    r = qa["other_c"].get(f"/api/share/answer/{qa['a']['id']}.png")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data[:4] == b"\x89PNG"
    r = qa["other_c"].get(f"/api/share/user/{qa['answerer']['username']}.png")
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"
    assert qa["other_c"].get("/api/share/answer/999999.png").status_code == 404
