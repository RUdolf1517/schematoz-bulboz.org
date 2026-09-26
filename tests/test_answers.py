"""Ответы: только текст, но код готов к голосовым/видео через фича-флаги."""


def test_capabilities_text_only(qa):
    r = qa["other_c"].get("/api/answers/capabilities")
    assert r.json["types"] == ["text"]


def test_voice_and_video_rejected_while_disabled(qa):
    for ct in ("voice", "video"):
        r = qa["other_c"].post(f"/api/questions/{qa['q']['id']}/answers",
                               json={"content_type": ct, "upload_id": "x"})
        assert r.status_code == 422
        assert r.json["error"] == "answer_type_disabled"


def test_unknown_type_rejected(qa):
    r = qa["other_c"].post(f"/api/questions/{qa['q']['id']}/answers",
                           json={"content_type": "hologram", "body": "hi"})
    assert r.status_code == 422 and r.json["error"] == "unknown_answer_type"


def test_text_validation(qa):
    url = f"/api/questions/{qa['q']['id']}/answers"
    assert qa["other_c"].post(url, json={"body": "   "}).status_code == 422
    assert qa["other_c"].post(url, json={"body": "x" * 5001}).status_code == 422
    assert qa["other_c"].post(url, json={"body": "ok", "upload_id": "u1"}).status_code == 422
    r = qa["other_c"].post(url, json={"body": "  нормальный ответ  "})
    assert r.status_code == 201
    assert r.json["answer"]["content"] == {"type": "text", "body": "нормальный ответ"}


def test_enabling_voice_flag_reaches_stub(qa, make_user):
    """Админ включил флаг — запрос доходит до заготовки-обработчика (NotImplementedError → 501).
    Это ожидаемо до реализации VoiceAnswerHandler; важно, что проводка работает."""
    admin_c, _ = make_user("admin")
    r = admin_c.put("/admin/settings/features", json={"value": {"ANSWER_VOICE_ENABLED": True}})
    assert r.status_code == 200
    assert "voice" in qa["other_c"].get("/api/answers/capabilities").json["types"]
    r = qa["other_c"].post(f"/api/questions/{qa['q']['id']}/answers",
                           json={"content_type": "voice", "upload_id": "x"})
    assert r.status_code == 501 and r.json["error"] == "not_implemented"


def test_debate_requires_side(make_user):
    c, _ = make_user("moderator")
    q = c.post("/api/questions", json={"kind": "debate", "title": "Шаверма или шаурма?"}).json["question"]
    assert q["debate"] == {"a": "За", "b": "Против"}
    c2, _ = make_user()
    url = f"/api/questions/{q['id']}/answers"
    assert c2.post(url, json={"body": "Шаверма, очевидно"}).status_code == 400
    r = c2.post(url, json={"body": "Шаверма, очевидно", "debate_side": "a"})
    assert r.status_code == 201 and r.json["answer"]["debate_side"] == "a"


def test_feed_shows_top_answer(qa):
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    items = qa["other_c"].get("/api/feed").json["items"]
    assert items[0]["id"] == qa["q"]["id"]
    assert items[0]["top_answer"]["is_best"] is True
