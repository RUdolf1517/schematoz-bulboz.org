def test_rooms_join_leave_and_my_rooms_feed(make_user):
    c, _ = make_user()
    rooms = c.get("/api/rooms").json["items"]
    assert len(rooms) >= 8 and all(r["joined"] is False for r in rooms)
    assert c.post("/api/rooms/genshin/join").json == {"joined": True, "member_count": 1}
    assert c.post("/api/rooms/genshin/join").json["member_count"] == 1   # идемпотентно
    room_id = c.get("/api/rooms/genshin").json["room"]["id"]
    c2, _ = make_user()
    c2.post("/api/questions", json={"title": "Кого качать первым?", "room_id": room_id})
    c2.post("/api/questions", json={"title": "Вопрос вне комнаты"})
    items = c.get("/api/feed?tab=my_rooms").json["items"]
    assert [q["title"] for q in items] == ["Кого качать первым?"]
    assert items[0]["room"] == {"slug": "genshin", "title": "Genshin Impact"}
    assert c.delete("/api/rooms/genshin/join").json == {"joined": False, "member_count": 0}
    assert c.get("/api/feed?tab=my_rooms").json["items"] == []


def test_anonymous_rooms_and_feed(app):
    c = app.test_client()
    assert c.get("/api/rooms").json["items"][0]["joined"] is None
    assert c.post("/api/rooms/genshin/join").status_code == 401
    assert c.get("/api/feed?tab=my_rooms").status_code == 401
    assert c.get("/api/feed?tab=nope").status_code == 400
    assert c.get("/api/rooms/nope").status_code == 404


def test_feed_tabs(qa, make_user):
    c, _ = make_user()
    c.post("/api/questions", json={"title": "Свежий вопрос без ответа"})
    unanswered = [q["title"] for q in c.get("/api/feed?tab=unanswered").json["items"]]
    assert unanswered == ["Свежий вопрос без ответа"]
    new = c.get("/api/feed?tab=new").json["items"]
    assert new[0]["title"] == "Свежий вопрос без ответа"
    room = c.get("/api/feed?room=ege-physics").json
    assert room["items"] == [] and room["next_offset"] is None
