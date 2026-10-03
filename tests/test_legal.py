FOOTER = ("разработано RUdolf1517 на основе технологий "
          '<a href="https://rudolfzinovev.xyz" rel="noopener">rudolfzinovev.xyz</a>')


def test_pages_and_footer(app):
    c = app.test_client()
    for slug in ("rules", "terms", "privacy", "requisites", ""):
        r = c.get(f"/{slug}")
        assert r.status_code == 200, slug
        assert FOOTER in r.get_data(as_text=True)
    assert "ООО «СукИнЭндСын»" in c.get("/requisites").get_data(as_text=True)


def test_admin_edits_legal_with_versions(make_user, app):
    admin_c, _ = make_user("admin")
    user_c, _ = make_user()
    body = {"body_md": "## Новые правила\n<script>alert(1)</script>Будь человеком."}
    assert user_c.put("/admin/legal/rules", json=body).status_code == 403
    r = admin_c.put("/admin/legal/rules", json=body)
    assert r.status_code == 200 and r.json["version"] == 2
    html = app.test_client().get("/rules").get_data(as_text=True)
    assert "Новые правила" in html and "<script>alert" not in html
    assert len(admin_c.get("/admin/legal/rules/versions").json["items"]) == 2


def test_captcha_page_has_footer(app):
    import re
    html = app.test_client().get("/kremle/challenge").get_data(as_text=True)
    text = re.sub(r"<[^>]+>", "", html)
    assert "разработано RUdolf1517 на основе технологий rudolfzinovev.xyz" in text
    assert 'href="https://rudolfzinovev.xyz"' in html
    assert "{{ questions_json }}" not in html and '"questions"' in html
