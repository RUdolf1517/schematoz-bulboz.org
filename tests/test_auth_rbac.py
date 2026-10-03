from kremle_detect.integrations.flask_ext import SESSION_KEY
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


def test_no_moderator_role(app, make_user):
    from app.permissions import ROLES
    assert set(ROLES) == {"user", "admin"}
    admin_c, _ = make_user("admin")
    c, victim = make_user()
    assert c.get("/mod/users?q=ab").status_code == 403              # баны — только админ
    assert admin_c.get("/mod/users?q=ab").status_code == 200
    assert admin_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "спам", "days": None}).status_code == 201
    assert admin_c.put(f"/admin/users/{victim['id']}/roles", json={"roles": ["user", "moderator"]}).status_code == 400
    r = app.test_client().get("/mod")
    assert r.status_code == 301 and r.headers["Location"].endswith("/admin#users")


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


def test_change_password(app, make_user):
    c, u = make_user()
    other = app.test_client()
    pass_captcha(other)
    assert other.post("/api/auth/login", json={"login": u["username"], "password": "correct-horse"}).status_code == 200
    assert app.test_client().post("/api/auth/password", json={}).status_code == 401
    bad = [({"current_password": "nope-nope", "new_password": "new-secret-1"}, "invalid_password"),
           ({"current_password": "correct-horse", "new_password": "short"}, "validation_error"),
           ({"current_password": "correct-horse", "new_password": "correct-horse"}, "same_password"),
           ({"current_password": "correct-horse", "new_password": " spaced-pass "}, "validation_error"),
           ({"current_password": "correct-horse", "new_password": "x" * 129}, "validation_error")]
    for body, err in bad:
        r = c.post("/api/auth/password", json=body)
        assert r.status_code == 400 and (err is None or r.json["error"] == err), (body, r.json)
    r = c.post("/api/auth/password", json={"current_password": "correct-horse", "new_password": "new-secret-1"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").status_code == 200                 # текущая сессия жива
    assert other.get("/api/auth/me").status_code == 401             # остальные выкинуты
    fresh = app.test_client()
    pass_captcha(fresh)
    assert fresh.post("/api/auth/login", json={"login": u["username"], "password": "correct-horse"}).status_code == 401
    pass_captcha(fresh)
    assert fresh.post("/api/auth/login", json={"login": u["username"], "password": "new-secret-1"}).status_code == 200


def test_change_password_bruteforce_captcha(make_user):
    c, _ = make_user()
    with c.session_transaction() as sess:      # убираем «запасную» капчу с регистрации
        sess.pop(SESSION_KEY, None)
    for _ in range(6):
        c.post("/api/auth/password", json={"current_password": "wrong-pass", "new_password": "new-secret-1"})
    r = c.post("/api/auth/password", json={"current_password": "correct-horse", "new_password": "new-secret-1"})
    assert r.status_code == 403 and r.json["error"] == "captcha_required"
    pass_captcha(c)
    assert c.post("/api/auth/password", json={"current_password": "correct-horse", "new_password": "new-secret-1"}).status_code == 200
