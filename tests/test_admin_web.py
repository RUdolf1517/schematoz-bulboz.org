import pytest


def test_captcha_settings_validated_and_applied(app, make_user):
    admin_c, _ = make_user("admin")
    assert admin_c.get("/admin/settings/captcha").json["value"]["question_count"] == app.config["KREMLE_QUESTION_COUNT"]
    bad = [{"categories": []}, {"categories": ["chemistry"]}, {"question_count": 0},
           {"question_count": 3, "max_errors": 3}]
    for value in bad:
        assert admin_c.put("/admin/settings/captcha", json={"value": value}).status_code == 400, value
    r = admin_c.put("/admin/settings/captcha", json={"value": {"categories": ["math"], "question_count": 3, "max_errors": 0}})
    assert r.status_code == 200
    assert app.test_client().get("/kremle/challenge").status_code == 200
    engine = app.extensions["kremle"].engine
    assert (engine.categories, engine.question_count, engine.max_errors) == (["math"], 3, 0)


def test_admin_users_search(make_user):
    admin_c, _ = make_user("admin")
    make_user(username="findme_1")
    items = admin_c.get("/admin/users?q=findme").json["items"]
    assert [u["username"] for u in items] == ["findme_1"]
    assert admin_c.get("/admin/users?q=%25").json["items"] == []   # % экранируется


@pytest.mark.parametrize("path", ["/", "/market", "/faq", "/u/someone", "/login", "/register",
                                  "/banned", "/mod", "/admin", "/rules"])
def test_pages_render_with_header_and_footer(app, path):
    r = app.test_client().get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="login-btn"' in html and ">Войти<" in html
    assert "разработано RUdolf1517" in html


def test_header_shows_user_menu_when_logged_in(make_user):
    c, _ = make_user()
    html = c.get("/").get_data(as_text=True)
    assert 'id="user-menu"' in html and 'id="login-btn"' not in html


@pytest.mark.parametrize("path", ["/q/1", "/ask", "/rooms", "/tasks", "/search"])
def test_qa_pages_gone(app, path):
    assert app.test_client().get(path).status_code == 404


def test_kombucha_redirects_home(app):
    r = app.test_client().get("/kombucha")
    assert r.status_code in (301, 302) and r.headers["Location"].endswith("/")


@pytest.mark.parametrize("nxt,expected", [("/market", "/market"), ("https://evil.com", "/"), ("//evil.com", "/"),
                                          ("javascript:alert(1)", "/")])
def test_no_open_redirect(app, nxt, expected):
    c = app.test_client()
    html = c.get(f"/login?next={nxt}").get_data(as_text=True)
    assert f'data-next="{expected}"' in html
    c.get(f"/captcha?next={nxt}")
    from kremle_detect.integrations.flask_ext import NEXT_KEY
    with c.session_transaction() as s:
        assert s[NEXT_KEY] == expected


def test_demo_accounts_hidden_by_default(app):
    assert "admin-demo-2026" not in app.test_client().get("/login").get_data(as_text=True)
