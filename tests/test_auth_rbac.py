from tests.conftest import pass_captcha


def test_register_and_login_without_captcha(app):
    c = app.test_client()
    r = c.post("/api/auth/register", json={"username": "nocaptcha", "email": "n@x.ru",
                                           "password": "12345678", "birth_year": 2005,
                                           "accept_terms": True})
    assert r.status_code == 201, r.json
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"login": "nocaptcha", "password": "12345678"}).status_code == 200


def test_bruteforce_triggers_captcha(app, make_user):
    make_user(username="victim2")
    c = app.test_client()
    bad = {"login": "victim2", "password": "wrong-password"}
    for _ in range(6):
        assert c.post("/api/auth/login", json=bad).status_code == 401
    good = {"login": "victim2", "password": "correct-horse"}
    r = c.post("/api/auth/login", json=good)
    assert r.status_code == 403 and r.json["error"] == "captcha_required"
    pass_captcha(c)
    assert c.post("/api/auth/login", json=good).status_code == 200


def test_too_young(app):
    c = app.test_client()
    pass_captcha(c)
    r = c.post("/api/auth/register", json={"username": "kid", "email": "k@x.ru",
                                           "password": "12345678", "birth_year": 2020,
                                           "accept_terms": True})
    assert r.status_code == 403 and r.json["error"] == "too_young"


def test_anonymous_cannot_post(app):
    c = app.test_client()
    assert c.post("/api/trades", json={}).status_code == 401
    assert c.post("/api/kombucha/plant", json={}).status_code == 401


def test_user_cannot_access_mod_or_admin(make_user):
    c, _ = make_user()
    assert c.get("/mod/users?q=ab").status_code == 403
    assert c.get("/admin/analytics").status_code == 403
    assert c.get("/admin/modlog").status_code == 403


def test_moderator_limits(make_user):
    mod_c, _ = make_user("moderator")
    _, victim = make_user()
    assert mod_c.get("/mod/users?q=ab").status_code == 200
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
    r = c.post("/api/market/999/buy", json={})
    assert r.status_code == 403 and r.json["error"] == "captcha_required"
    pass_captcha(c)
    assert c.post("/api/market/999/buy", json={}).status_code == 404
    assert c.post("/api/market/998/buy", json={}).status_code == 404
