"""FAQ и кастомизация профиля."""


def test_faq_page_and_api(app):
    client = app.test_client()
    r = client.get("/faq")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "faq-item" in html and "<details" in html
    assert client.get("/api/legal/faq").status_code == 200


def test_faq_split():
    from app.legal import faq_split
    intro, items = faq_split("Привет\n\n## Что это?\nСайт\n\n## Как?\nТак")
    assert intro.strip() == "Привет"
    assert [q for q, _ in items] == ["Что это?", "Как?"]


def _patch(c, **body):
    return c.patch("/api/me/profile", json=body)


def test_profile_update_validation(make_user):
    c, _ = make_user()
    d = c.get("/api/me/profile").get_json()
    assert "themes" in d["options"]
    assert _patch(c, theme="neon", accent="#00FF00", status_emoji="😎", status_text="ЕГЭ скоро",
                  interests=["аниме", "#Аниме", "физика"], links=[{"title": "tg", "url": "https://t.me/x"}]).status_code == 200
    s = c.get("/api/me/profile").get_json()["settings"]
    assert s["theme"] == "neon" and s["accent"] == "#00ff00" and s["interests"] == ["аниме", "физика"]
    assert _patch(c, accent="red; background:url(x)").status_code == 400
    assert _patch(c, theme="<script>").status_code == 400
    assert _patch(c, links=[{"url": "javascript:alert(1)"}]).status_code == 400
    assert _patch(c, avatar_url="https://evil.example/a.png").status_code == 400
    assert _patch(c, avatar_url="/media/" + "0" * 32 + ".webp").status_code == 400
    assert _patch(c, showcase_badges=["no_such_badge"]).status_code == 400
    assert _patch(c, pinned_answer_id=999999).status_code == 400
    assert _patch(c, avatar_frame="rainbow").status_code == 403
    assert _patch(c, status_emoji="abc").status_code == 400


def test_hidden_sections_not_leaked(app, make_user):
    c, _ = make_user()
    me = c.get("/api/me/profile").get_json()["user"]["username"]
    assert _patch(c, hidden_sections=["badges", "follows", "streak"]).status_code == 200
    own = c.get(f"/api/users/{me}").get_json()
    assert own["is_owner"] and "followers" in own["stats"]
    other = app.test_client().get(f"/api/users/{me}").get_json()
    assert other["badges"] == [] and "followers" not in other["stats"] and other["user"]["streak_days"] is None


def test_pin_only_own_answer(qa):
    assert _patch(qa["author_c"], pinned_answer_id=qa["a"]["id"]).status_code == 400
    assert _patch(qa["answerer_c"], pinned_answer_id=qa["a"]["id"]).status_code == 200
    d = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").get_json()
    assert d["pinned_answer"]["answer_id"] == qa["a"]["id"]


def test_settings_page_requires_login(app, make_user):
    assert app.test_client().get("/settings").status_code == 302
    c, _ = make_user()
    assert c.get("/settings").status_code == 200
