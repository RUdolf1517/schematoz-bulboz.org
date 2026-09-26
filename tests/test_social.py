"""Уведомления, подписки, поиск, редактирование/удаление."""


def kinds(client):
    return [n["kind"] for n in client.get("/api/notifications").json["items"]]


def test_notifications_flow(qa, make_user):
    # ответ на вопрос → автору вопроса; первый ответ → бейдж отвечающему
    assert "answer" in kinds(qa["author_c"])
    n = qa["author_c"].get("/api/notifications").json["items"][0]
    assert n["payload"]["answer_id"] == qa["a"]["id"] and n["payload"]["username"] == qa["answerer"]["username"]
    assert "badge" in kinds(qa["answerer_c"])
    # +5 → «Схема» и бейдж автору ответа
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    k = kinds(qa["answerer_c"])
    assert "scheme" in k and k.count("badge") == 2
    me = qa["answerer_c"].get("/api/auth/me").json
    assert me["unread_notifications"] == 3
    # прочитать одно, потом все
    first = qa["answerer_c"].get("/api/notifications").json["items"][0]["id"]
    assert qa["answerer_c"].post("/api/notifications/read", json={"ids": [first]}).json["unread"] == 2
    assert qa["answerer_c"].post("/api/notifications/read", json={}).json["unread"] == 0
    assert qa["answerer_c"].post("/api/notifications/read", json={"ids": "x"}).status_code == 400
    # на свой вопрос себе уведомление не шлём
    qa["author_c"].post(f"/api/questions/{qa['q']['id']}/answers", json={"body": "Сам спросил — сам ответил"})
    assert kinds(qa["author_c"]).count("answer") == 1


def test_notifications_are_private(qa):
    assert qa["other_c"].get("/api/notifications").json["items"] == [] or \
        all(n["kind"] != "answer" for n in qa["other_c"].get("/api/notifications").json["items"])
    other_ids = [n["id"] for n in qa["author_c"].get("/api/notifications").json["items"]]
    qa["other_c"].post("/api/notifications/read", json={"ids": other_ids})
    assert qa["author_c"].get("/api/auth/me").json["unread_notifications"] == len(other_ids)


def test_ban_and_appeal_notifications(make_user):
    mod_c, _ = make_user("moderator")
    admin_c, _ = make_user("admin")
    v_c, v = make_user(username="notified")
    ban_id = mod_c.post("/mod/bans", json={"user_id": v["id"], "reason": "спам", "days": 1}).json["ban_id"]
    from tests.conftest import pass_captcha
    pass_captcha(v_c)
    v_c.post("/api/auth/login", json={"login": "notified", "password": "correct-horse"})
    assert kinds(v_c)[0] == "ban"
    v_c.post(f"/api/bans/{ban_id}/appeal", json={"text": "Пожалуйста, разберитесь"})
    admin_c.post(f"/mod/appeals/{ban_id}/decide", json={"decision": "reject", "comment": "Нет"})
    n = v_c.get("/api/notifications").json["items"][0]
    assert n["kind"] == "appeal" and n["payload"]["decision"] == "reject"


def test_follow_and_following_feed(make_user):
    a_c, a = make_user(username="fan")
    b_c, b = make_user(username="star")
    assert a_c.put("/api/users/fan/follow").status_code == 400
    r = a_c.put("/api/users/star/follow")
    assert r.json == {"following": True, "followers": 1, "following_count": 0} or r.json["followers"] == 1
    a_c.put("/api/users/star/follow")                       # идемпотентно
    assert kinds(b_c).count("follow") == 1
    prof = a_c.get("/api/users/star").json
    assert prof["i_follow"] is True and prof["stats"]["followers"] == 1
    assert a_c.get("/api/users/fan").json["i_follow"] is None   # свой профиль
    b_c.post("/api/questions", json={"title": "Вопрос от звезды"})
    make_user()[0].post("/api/questions", json={"title": "Вопрос от ноунейма"})
    assert [q["title"] for q in a_c.get("/api/feed?tab=following").json["items"]] == ["Вопрос от звезды"]
    a_c.delete("/api/users/star/follow")
    assert a_c.get("/api/feed?tab=following").json["items"] == []
    assert a_c.put("/api/users/nobody/follow").status_code == 404


def test_search(make_user):
    c, _ = make_user()
    c.post("/api/questions", json={"title": "Почему шарики падают с ускорением?"})
    c.post("/api/questions", json={"title": "Как пожарить воду на сковородке?", "body": "очень хочется"})
    # морфология: «шарик» находит «шарики», «сковородка» — «сковородке»
    r = c.get("/api/search?q=шарик").json
    assert r["mode"] == "fulltext" and [q["title"] for q in r["items"]] == ["Почему шарики падают с ускорением?"]
    assert len(c.get("/api/search?q=сковородка").json["items"]) == 1
    assert c.get("/api/search?q=хочется").json["items"][0]["title"].startswith("Как пожарить")  # по body
    assert c.get("/api/search?q=зарик").json["items"] == []
    assert c.get("/api/search?q=о").status_code == 400
    assert c.get("/api/search?q=%25%25").status_code == 200


def test_edit_question_rules(qa, make_user):
    url = f"/api/questions/{qa['q']['id']}"
    # у вопроса уже есть ответ — заголовок заблокирован, подробности можно
    r = qa["author_c"].patch(url, json={"title": "Совсем другой вопрос теперь"})
    assert r.status_code == 409 and r.json["error"] == "title_locked"
    r = qa["author_c"].patch(url, json={"body": "Уточняю: в вакууме"})
    assert r.status_code == 200 and r.json["question"]["body"] == "Уточняю: в вакууме"
    assert r.json["question"]["edited_at"] is not None
    assert qa["other_c"].patch(url, json={"body": "взлом"}).status_code == 403
    # новый вопрос без ответов — заголовок менять можно
    q2 = qa["author_c"].post("/api/questions", json={"title": "Черновой заголовок"}).json["question"]
    r = qa["author_c"].patch(f"/api/questions/{q2['id']}", json={"title": "Нормальный заголовок"})
    assert r.status_code == 200 and r.json["question"]["title"] == "Нормальный заголовок"


def test_delete_question_rules(qa):
    url = f"/api/questions/{qa['q']['id']}"
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    r = qa["author_c"].delete(url)
    assert r.status_code == 409 and r.json["error"] == "has_scheme"
    q2 = qa["author_c"].post("/api/questions", json={"title": "Удалю этот вопрос"}).json["question"]
    assert qa["other_c"].delete(f"/api/questions/{q2['id']}").status_code == 403
    assert qa["author_c"].delete(f"/api/questions/{q2['id']}").status_code == 200
    assert qa["other_c"].get(f"/api/questions/{q2['id']}").status_code == 404


def test_edit_and_delete_answer(qa):
    aid, url = qa["a"]["id"], f"/api/answers/{qa['a']['id']}"
    r = qa["answerer_c"].patch(url, json={"body": "Исправленный ответ: F = mg"})
    assert r.status_code == 200 and r.json["answer"]["edited_at"]
    assert qa["other_c"].patch(url, json={"body": "чужое"}).status_code == 403
    # голос за ответ не должен ставить пометку «изменено» другому ответу
    qa["author_c"].put(f"/api/answers/{aid}/vote", json={"value": 5})
    rep_before = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json["user"]["reputation"]
    assert qa["answerer_c"].delete(url).status_code == 200
    q = qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json
    assert q["answers"] == [] and q["question"]["best_answer_id"] is None and q["question"]["answers_count"] == 0
    # репутация не откатывается при удалении
    assert qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json["user"]["reputation"] == rep_before
    assert qa["answerer_c"].patch(url, json={"body": "воскрешение"}).status_code == 404


def test_vote_does_not_mark_edited(qa):
    qa["other_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 1})
    a = qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json["answers"][0]
    assert a["edited_at"] is None
