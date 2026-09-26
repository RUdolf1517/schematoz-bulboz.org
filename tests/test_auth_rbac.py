from tests.conftest import pass_captcha


def test_register_requires_captcha(app):
    c = app.test_client()
    r = c.post("/api/auth/register", json={"username": "bot", "email": "b@x.ru",
                                           "password": "12345678", "birth_year": 2000,
                                           "accept_terms": True})
    assert r.status_code == 403
    assert r.json["error"] == "captcha_required"
    assert r.json["challenge_url"] == "/kremle/challenge"


def test_captcha_is_consumed_per_login(app, make_user):
    c, user = make_user(username="dasha")
    c.post("/api/auth/logout")
    body = {"login": "dasha", "password": "correct-horse"}
    assert c.post("/api/auth/login", json=body).status_code == 403
    pass_captcha(c)
    assert c.post("/api/auth/login", json=body).status_code == 200
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json=body).status_code == 403  # капча снова нужна


def test_too_young(app):
    c = app.test_client()
    pass_captcha(c)
    r = c.post("/api/auth/register", json={"username": "kid", "email": "k@x.ru",
                                           "password": "12345678", "birth_year": 2020,
                                           "accept_terms": True})
    assert r.status_code == 403 and r.json["error"] == "too_young"


def test_anonymous_cannot_post(app):
    r = app.test_client().post("/api/questions", json={"title": "Как пожарить воду?"})
    assert r.status_code == 401


def test_user_cannot_access_mod_or_admin(make_user):
    c, _ = make_user()
    assert c.get("/mod/reports").status_code == 403
    assert c.get("/admin/analytics").status_code == 403
    assert c.get("/admin/modlog").status_code == 403


def test_moderator_limits(make_user):
    mod_c, _ = make_user("moderator")
    _, victim = make_user()
    assert mod_c.get("/mod/reports").status_code == 200
    assert mod_c.get("/admin/modlog").status_code == 403           # полный лог — только админ
    r = mod_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "спам", "days": None})
    assert r.status_code == 403                                     # перманент — только админ
    r = mod_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "спам", "days": 31})
    assert r.status_code == 403


def test_suspicious_activity_triggers_captcha(app, make_user):
    c, user = make_user()
    from app.services import antispam
    with app.test_request_context():
        antispam.mark_suspicious(f"u:{user['id']}", "test")
    r = c.post("/api/questions", json={"title": "Можно ли пожарить воду?"})
    assert r.status_code == 403 and r.json["error"] == "captcha_required"
    pass_captcha(c)
    assert c.post("/api/questions", json={"title": "Можно ли пожарить воду?"}).status_code == 201
    assert c.post("/api/questions", json={"title": "И ещё один вопрос?"}).status_code == 201
