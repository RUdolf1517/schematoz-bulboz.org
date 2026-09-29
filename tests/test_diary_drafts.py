"""Дневник гриба (публичный) и черновики вопросов/ответов."""
from tests.conftest import pass_captcha


def test_diary_logs_and_is_public(make_user, app):
    c, _ = make_user()
    kid = c.get("/api/kombucha").get_json()["items"][0]["id"]
    assert c.patch(f"/api/kombucha/{kid}", json={"name": "Дневничок"}).status_code == 200
    assert c.post(f"/api/kombucha/{kid}/freeze").status_code == 200
    d = app.test_client().get(f"/api/kombucha/{kid}/diary").get_json()      # аноним тоже видит
    kinds = [e["kind"] for e in d["items"]]
    assert kinds[:2] == ["frozen", "renamed"] and "born" in kinds and d["mine"] is False
    assert "Дневничок" in d["items"][1]["text"] and d["kombucha"]["name"] == "Дневничок"
    assert c.get(f"/api/kombucha/{kid}/diary").get_json()["mine"] is True
    assert app.test_client().get(f"/g/{kid}").status_code == 200
    assert app.test_client().get("/api/kombucha/999999/diary").status_code == 404


def test_question_draft_lifecycle(make_user):
    c, _ = make_user()
    c2, _ = make_user()
    pass_captcha(c)
    assert c.post("/api/drafts", json={"kind": "question", "title": "  ", "body": ""}).status_code == 400
    r = c.post("/api/drafts", json={"kind": "question", "title": "Как вырастить гриб?", "extra": {"kind": "knowledge", "evil": "x"}})
    assert r.status_code == 201
    d = r.get_json()["draft"]
    assert d["extra"] == {"kind": "knowledge"}
    assert c.put(f"/api/drafts/{d['id']}", json={"title": "Как вырастить гриб быстро?", "body": "подробно"}).status_code == 200
    assert c2.get(f"/api/drafts/{d['id']}").status_code == 404                  # чужой — не видно
    assert c2.delete(f"/api/drafts/{d['id']}").status_code == 404
    assert c.get("/api/drafts").get_json()["items"][0]["title"] == "Как вырастить гриб быстро?"
    q = c.post("/api/questions", json={"kind": "knowledge", "title": "Как вырастить гриб быстро?", "draft_id": d["id"]})
    assert q.status_code == 201
    assert c.get("/api/drafts").get_json()["items"] == []                        # опубликовал — черновик исчез


def test_answer_draft_upsert_and_publish(qa):
    c, qid = qa["other_c"], qa["q"]["id"]
    pass_captcha(c)
    a = c.post("/api/drafts", json={"kind": "answer", "question_id": qid, "body": "черно"}).get_json()["draft"]
    b = c.post("/api/drafts", json={"kind": "answer", "question_id": qid, "body": "черновик ответа"}).get_json()["draft"]
    assert a["id"] == b["id"]                                                    # один черновик на вопрос
    got = c.get(f"/api/drafts/answer/{qid}").get_json()["draft"]
    assert got["body"] == "черновик ответа"
    assert c.get("/api/drafts").get_json()["items"][0]["question_title"] == qa["q"]["title"]
    assert c.post(f"/api/questions/{qid}/answers", json={"body": "Готовый ответ про ускорение и g."}).status_code == 201
    assert c.get(f"/api/drafts/answer/{qid}").get_json()["draft"] is None
