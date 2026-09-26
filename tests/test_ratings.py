"""Рейтинги вопросов/юзеров, комментарии, markdown, картинки, холивары только для модеров."""
import io

from PIL import Image

from app.services.markdown import render
from app.services.rating import user_rating_formula, wilson_lower

BASE = dict(questions=0, answers=0, comments=0, comments_received=0, plus=0, minus=0, plus_votes=0,
            minus_votes=0, schemes=0, question_votes=0, active_days_30=0, idle_days=0, hidden=0,
            recent_ban=False)


def f(**kw):
    return user_rating_formula(**{**BASE, **kw})


# ───────────── формула
def test_formula_properties():
    assert f() == 0
    assert f(answers=1) > f(questions=1) > f(comments=1) > 0           # ответ ценнее вопроса ценнее коммента
    assert f(answers=100) - f(answers=99) < f(answers=1) - f(answers=0)  # убывающая отдача — флуд не окупается
    assert f(answers=5, plus=5, plus_votes=5) > f(answers=50)             # качество важнее количества
    assert f(answers=5, plus=4, minus=4, plus_votes=4, minus_votes=4) < f(answers=5)  # минус бьёт сильнее плюса
    assert f(answers=10, plus=300, plus_votes=300) > f(answers=10, plus=300, plus_votes=100, minus_votes=0) * 0.99
    assert wilson_lower(300, 0) > wilson_lower(3, 0)                      # больше оценок — больше доверия
    active = dict(answers=10, plus=20, plus_votes=20, schemes=2)
    assert abs(f(**active, active_days_30=30) - f(**active) * 1.5) < 0.2
    assert f(**active, idle_days=60) < f(**active) and f(**active, idle_days=10_000) >= f(**active) * 0.3 - 0.1
    assert f(**active, hidden=3) < f(**active) and abs(f(**active, recent_ban=True) - f(**active) / 2) < 0.2
    assert f(answers=1, minus=500, minus_votes=500) == 0                  # не уходит в минус


# ───────────── рейтинг вопроса
def test_question_votes_and_rating(qa, make_user):
    qid = qa["q"]["id"]
    url = f"/api/questions/{qid}/vote"
    assert qa["author_c"].put(url, json={"value": 1}).json["error"] == "own_question"
    assert qa["other_c"].put(url, json={"value": 5}).status_code == 400
    base = qa["other_c"].get(f"/api/questions/{qid}").json["question"]["rating"]
    assert base == 2  # 1 ответ = +2
    r = qa["other_c"].put(url, json={"value": 1}).json
    assert r["votes_score"] == 1 and r["rating"] == base + 1
    assert qa["other_c"].put(url, json={"value": -1}).json["votes_score"] == -1   # перевыбор
    assert qa["other_c"].delete(url).json["votes_score"] == 0
    qa["other_c"].put(url, json={"value": 1})
    q = qa["other_c"].get(f"/api/questions/{qid}").json["question"]
    assert q["my_vote"] == 1 and q["votes_score"] == 1
    # комментарий к ответу тоже поднимает рейтинг вопроса (+0.5)
    qa["other_c"].post(f"/api/answers/{qa['a']['id']}/comments", json={"body": "плюсую"})
    assert qa["other_c"].get(f"/api/questions/{qid}").json["question"]["rating"] == base + 1 + 0.5


def test_top_feed_orders_by_rating(make_user):
    a, _ = make_user()
    voters = [make_user()[0] for _ in range(3)]
    low = a.post("/api/questions", json={"title": "Скучный вопрос"}).json["question"]["id"]
    high = a.post("/api/questions", json={"title": "Годный вопрос"}).json["question"]["id"]
    for v in voters:
        v.put(f"/api/questions/{high}/vote", json={"value": 1})
    voters[0].put(f"/api/questions/{low}/vote", json={"value": -1})
    ids = [q["id"] for q in a.get("/api/feed?tab=top").json["items"]]
    assert ids.index(high) < ids.index(low)


# ───────────── комментарии
def test_comments(qa):
    aid, qid = qa["a"]["id"], qa["q"]["id"]
    url = f"/api/answers/{aid}/comments"
    assert qa["other_c"].post(url, json={"body": "x" * 201}).status_code == 400
    r = qa["other_c"].post(url, json={"body": "**жирно** и `код` <script>alert(1)</script>\n# заголовок"})
    assert r.status_code == 201
    html = r.json["comment"]["body_html"]
    assert "<strong>жирно</strong>" in html and "<code>код</code>" in html
    assert "<script" not in html and "<h" not in html  # в комментах нет заголовков
    assert "comment" in [n["kind"] for n in qa["answerer_c"].get("/api/notifications").json["items"]]
    q = qa["other_c"].get(f"/api/questions/{qid}").json
    assert q["answers"][0]["comments_count"] == 1 and q["answers"][0]["comments"][0]["body_html"] == html
    cid = r.json["comment"]["id"]
    assert qa["author_c"].delete(f"/api/comments/{cid}").status_code == 403
    assert qa["other_c"].patch(f"/api/comments/{cid}", json={"body": "поправил"}).json["comment"]["edited_at"]
    assert qa["other_c"].delete(f"/api/comments/{cid}").status_code == 200
    q = qa["other_c"].get(f"/api/questions/{qid}").json
    assert q["answers"][0]["comments"] == [] and q["question"]["comments_count"] == 0


def test_comments_ordered_by_author_rating(qa, make_user):
    aid = qa["a"]["id"]
    url = f"/api/answers/{aid}/comments"
    admin_c, _ = make_user("admin")
    mod_c, _ = make_user("moderator")
    qa["other_c"].post(url, json={"body": "юзер первый"})
    admin_c.post(url, json={"body": "админ"})
    mod_c.post(url, json={"body": "модер"})
    bodies = [c["body"] for c in qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json["answers"][0]["comments"]]
    assert bodies == ["админ", "модер", "юзер первый"]


def test_moderator_hides_comment(qa, make_user):
    mod_c, _ = make_user("moderator")
    cid = qa["other_c"].post(f"/api/answers/{qa['a']['id']}/comments", json={"body": "спам"}).json["comment"]["id"]
    assert mod_c.post(f"/mod/content/comment/{cid}/hide", json={}).status_code == 200
    q = qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json
    assert q["answers"][0]["comments_count"] == 0 and q["question"]["comments_count"] == 0
    mod_c.post(f"/mod/content/comment/{cid}/restore", json={})
    assert qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json["question"]["comments_count"] == 1
    assert qa["author_c"].post("/api/reports", json={"target_type": "comment", "target_id": cid,
                                                     "reason": "spam"}).status_code == 201


# ───────────── рейтинг юзера и порядок ответов
def test_user_rating_and_tiers(qa, make_user):
    admin_c, admin = make_user("admin")
    mod_c, mod = make_user("moderator")
    assert admin["rating_display"] == "∞" or admin_c.get("/api/auth/me").json["user"]["rating_display"] == "∞"
    a_me = admin_c.get("/api/auth/me").json["user"]
    m_me = mod_c.get("/api/auth/me").json["user"]
    assert (a_me["rating"], a_me["rating_tier"]) == (None, 2) and (m_me["rating"], m_me["rating_tier"]) == (None, 1)
    before = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json["user"]["rating"]
    assert before > 0
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    after = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json["user"]["rating"]
    assert after > before  # «Схема» поднимает рейтинг


def test_answers_ordered_by_tier_then_rating(qa, make_user):
    qid = qa["q"]["id"]
    admin_c, _ = make_user("admin")
    mod_c, _ = make_user("moderator")
    mod_c.post(f"/api/questions/{qid}/answers", json={"body": "ответ модера"})
    admin_c.post(f"/api/questions/{qid}/answers", json={"body": "ответ админа"})
    qa["other_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 1})
    bodies = [a["content"]["body"] for a in qa["other_c"].get(f"/api/questions/{qid}").json["answers"]]
    assert bodies[:2] == ["ответ админа", "ответ модера"]
    # «Схема» (выбор автора вопроса) всё равно первой
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    first = qa["other_c"].get(f"/api/questions/{qid}").json["answers"][0]
    assert first["id"] == qa["a"]["id"] and first["is_best"]


# ───────────── холивары
def test_debates_only_for_mods(make_user):
    u, _ = make_user()
    r = u.post("/api/questions", json={"kind": "debate", "title": "Кошки или собаки?"})
    assert r.status_code == 403
    m, _ = make_user("moderator")
    assert m.post("/api/questions", json={"kind": "debate", "title": "Кошки или собаки?"}).status_code == 201
    u.post("/api/questions", json={"title": "Обычный вопрос тут"})
    items = u.get("/api/feed?tab=debates").json["items"]
    assert [q["kind"] for q in items] == ["debate"]
    assert u.get("/debates").status_code == 200


# ───────────── markdown и картинки
def test_markdown_sanitizing():
    html = render("# Big\n\n[x](javascript:alert(1)) ![a](https://evil.example/t.png) "
                  "![b](/media/" + "a" * 32 + ".webp) <img src=x onerror=alert(1)>")
    assert "<h3>" in html and "<h1>" not in html
    assert "javascript:" not in html and "evil.example" not in html and "onerror" not in html
    assert f'src="/media/{"a" * 32}.webp"' in html and 'loading="lazy"' in html
    assert 'rel="nofollow ugc noopener"' in render("[сайт](https://example.com)")


def _png(size=(40, 30), exif=False):
    img = Image.new("RGB", size, (200, 30, 90))
    buf = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"
        img.save(buf, "JPEG", exif=ex)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def test_upload_and_cover(app, make_user, tmp_path):
    app.config["UPLOAD_DIR"] = str(tmp_path)
    c, _ = make_user()
    r = c.post("/api/uploads", data={"file": (io.BytesIO(_png((3000, 1500), exif=True)), "a.jpg")},
               content_type="multipart/form-data")
    assert r.status_code == 201, r.json
    url = r.json["url"]
    assert url.startswith("/media/") and url.endswith(".webp") and r.json["width"] == 1600
    img = c.get(url)
    assert img.status_code == 200 and img.mimetype == "image/webp"
    assert b"SecretCam" not in img.data
    assert c.post("/api/uploads", data={"file": (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg")},
                  content_type="multipart/form-data").json["error"] == "invalid_image"
    assert c.get("/media/../../etc/passwd").status_code == 404
    # обложка
    q = c.post("/api/questions", json={"title": "Вопрос с обложкой", "cover_url": url,
                                       "body": f"смотри ![]({url})"}).json["question"]
    assert q["cover_url"] == url and f'src="{url}"' in q["body_html"]
    other, _ = make_user()
    assert other.post("/api/questions", json={"title": "Чужая обложка", "cover_url": url}).status_code == 400
    assert c.post("/api/questions", json={"title": "Внешняя обложка",
                                          "cover_url": "https://evil.example/a.png"}).status_code == 400
    assert c.patch(f"/api/questions/{q['id']}", json={"cover_url": None}).json["question"]["cover_url"] is None
    assert c.get("/api/feed?tab=new").json["items"][0]["cover_url"] is None
    # анонимам грузить нельзя
    assert app.test_client().post("/api/uploads").status_code == 401
