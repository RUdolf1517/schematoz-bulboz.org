def test_appeal_flow(make_user):
    admin_c, admin = make_user("admin")
    victim_c, victim = make_user(username="victim")
    ban_id = admin_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "спам", "days": 7}).json["ban_id"]

    # забаненный может войти, но не может постить
    from tests.conftest import pass_captcha
    pass_captcha(victim_c)
    r = victim_c.post("/api/auth/login", json={"login": "victim", "password": "correct-horse"})
    assert r.status_code == 200 and r.json["banned"] is True
    assert victim_c.post("/api/market/999/buy", json={}).json["error"] == "banned"
    assert victim_c.get("/api/kombucha").json["error"] == "banned"
    assert victim_c.get("/api/auth/me").json["ban"]["id"] == ban_id
    assert victim_c.get("/api/me/ban").json["ban"]["reason"] == "спам"
    for path in ("/market", "/rules"):
        blocked_page = victim_c.get(path, follow_redirects=False)
        assert blocked_page.status_code == 302 and blocked_page.headers["Location"].endswith("/banned")
    ban_page = victim_c.get("/banned").get_data(as_text=True)
    assert 'class="main-nav"' not in ban_page and 'class="site-footer"' not in ban_page
    assert 'id="toast"' not in ban_page and 'id="banned"' in ban_page

    assert victim_c.post(f"/api/bans/{ban_id}/appeal", json={"text": "коротко"}).status_code == 400
    assert victim_c.post(f"/api/bans/{ban_id}/appeal", json={"text": "Это был не спам, а ссылка на учебник"}).status_code == 200
    assert victim_c.post(f"/api/bans/{ban_id}/appeal", json={"text": "Ещё раз прошу разобраться"}).status_code == 409

    # модераторов нет: админ разбирает и свои баны (помечены own)
    items = admin_c.get("/mod/appeals").json["items"]
    assert [a["ban_id"] for a in items] == [ban_id] and items[0]["own"] is True
    assert victim_c.get("/mod/appeals").status_code == 403
    r = admin_c.post(f"/mod/appeals/{ban_id}/decide", json={"decision": "accept", "comment": "Разобрались"})
    assert r.json["appeal_status"] == "accepted"
    assert victim_c.get("/api/me/ban").json["ban"] is None
    assert victim_c.post("/api/market/999/buy", json={}).status_code == 404   # бан снят — дошли до поиска лота
    log = [a["action"] for a in admin_c.get("/admin/modlog").json["items"]]
    assert "appeal.accept" in log and "ban.issue" in log


def test_foreign_ban_cannot_be_appealed(make_user):
    admin_c, _ = make_user("admin")
    _, victim = make_user()
    other_c, _ = make_user()
    ban_id = admin_c.post("/mod/bans", json={"user_id": victim["id"], "reason": "x", "days": 1}).json["ban_id"]
    assert other_c.post(f"/api/bans/{ban_id}/appeal", json={"text": "это не мой бан, но всё же"}).status_code == 404
