"""Файл входа."""
from tests.conftest import pass_captcha


def test_login_file_flow(app, make_user):
    c, u = make_user(username="keyholder")
    r = c.post("/api/auth/login-keys", json={"label": "Ноутбук"})
    assert r.status_code == 201
    f = r.json["file"]
    assert f["type"] == "schematoz-bulboz-login-key" and f["username"] == "keyholder" and f["key"].startswith("sbk_")
    assert r.json["filename"] == "bulboz-keyholder.key"
    # в списке ключа нет — только метаданные
    items = c.get("/api/auth/login-keys").json["items"]
    assert items[0]["label"] == "Ноутбук" and "key" not in items[0] and items[0]["last_used_at"] is None

    fresh = app.test_client()
    assert fresh.get("/api/auth/me").status_code == 401
    r = fresh.post("/api/auth/login-file", json={"file": f})
    assert r.status_code == 200 and r.json["user"]["username"] == "keyholder"
    assert fresh.get("/api/auth/me").json["user"]["username"] == "keyholder"
    assert c.get("/api/auth/login-keys").json["items"][0]["last_used_at"]

    # отзыв
    kid = items[0]["id"]
    assert c.delete(f"/api/auth/login-keys/{kid}").json["revoked"]
    r = app.test_client().post("/api/auth/login-file", json={"key": f["key"]})
    assert r.status_code == 401 and r.json["error"] == "invalid_key"


def test_login_key_isolation_and_limits(app, make_user):
    a, _ = make_user()
    b, _ = make_user()
    kid = a.post("/api/auth/login-keys", json={}).json["key"]["id"]
    assert b.delete(f"/api/auth/login-keys/{kid}").status_code == 404
    assert app.test_client().post("/api/auth/login-keys", json={}).status_code == 401
    for _ in range(4):
        a.post("/api/auth/login-keys", json={})
    assert a.post("/api/auth/login-keys", json={}).json["error"] == "too_many_keys"
    assert app.test_client().post("/api/auth/login-file", json={"key": "garbage"}).json["error"] == "invalid_key_file"


def test_login_file_bruteforce_triggers_captcha(app):
    c = app.test_client()
    for _ in range(6):
        c.post("/api/auth/login-file", json={"key": "sbk_wrongwrongwrong"})
    r = c.post("/api/auth/login-file", json={"key": "sbk_wrongwrongwrong"})
    assert r.json["error"] == "captcha_required"
    pass_captcha(c)
    assert c.post("/api/auth/login-file", json={"key": "sbk_wrongwrongwrong"}).json["error"] == "invalid_key"
