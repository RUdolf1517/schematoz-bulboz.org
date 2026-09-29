from datetime import date, datetime, timedelta

from app.services.gamification import iso_week, level_name, next_streak, visible_streak

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
    assert level_name(1) == "Грибной нуб" and level_name(12) == "Заварщик"


def test_care_moves_streak_and_level(make_user, app):
    c, u = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    assert c.post(f"/api/kombucha/{kid}/pet").status_code == 200
    me = c.get(f"/api/users/{u['username']}").get_json()
    assert me["user"]["streak_days"] == 1
    assert me["stats"]["kombuchas"] == 1 and me["garden"][0]["id"] == kid
