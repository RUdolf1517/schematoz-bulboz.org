"""Правило репутации: автор вопроса — только +5 или −1; остальные — только ±1."""
import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def rep(client, username):
    return client.get(f"/api/users/{username}").json["user"]["reputation"]


@pytest.mark.parametrize("value", [5, -1])
def test_author_allowed_values(qa, value):
    r = qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": value})
    assert r.status_code == 200, r.json
    assert r.json["score"] == value
    assert r.json["is_best"] is (value == 5)


@pytest.mark.parametrize("value", [1, 2, 3, 4, 6, 7, 0, -2, -5])
def test_author_forbidden_values(qa, value):
    r = qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": value})
    assert r.status_code == 400
    assert r.json["error"] == "invalid_vote_value"
    assert r.json["allowed"] == [5, -1]


@pytest.mark.parametrize("value", [1, -1])
def test_others_allowed_values(qa, value):
    r = qa["other_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": value})
    assert r.status_code == 200
    assert r.json["is_best"] is False


@pytest.mark.parametrize("value", [5, 2, 0, -5])
def test_others_forbidden_values(qa, value):
    r = qa["other_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": value})
    assert r.status_code == 400
    assert r.json["allowed"] == [1, -1]


def test_cannot_vote_own_answer(qa):
    r = qa["answerer_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 1})
    assert r.status_code == 400 and r.json["error"] == "own_answer"


def test_bool_is_not_a_vote(qa):
    r = qa["other_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": True})
    assert r.status_code == 400


def test_reputation_accumulates_and_changes(qa):
    c, a, name = qa["other_c"], qa["a"]["id"], qa["answerer"]["username"]
    qa["author_c"].put(f"/api/answers/{a}/vote", json={"value": 5})
    c.put(f"/api/answers/{a}/vote", json={"value": 1})
    assert rep(c, name) == 6
    # автор передумал: +5 → −1, «Схема» снимается
    r = qa["author_c"].put(f"/api/answers/{a}/vote", json={"value": -1})
    assert r.json["is_best"] is False and r.json["score"] == 0
    assert rep(c, name) == 0
    # снятие голоса
    qa["other_c"].delete(f"/api/answers/{a}/vote")
    assert rep(c, name) == 0  # 0 в профиле (внутри −1, но ниже нуля не показываем)


def test_best_answer_is_the_last_plus5(qa, make_user):
    c2, _ = make_user()
    a2 = c2.post(f"/api/questions/{qa['q']['id']}/answers", json={"body": "Второй ответ"}).json["answer"]
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    qa["author_c"].put(f"/api/answers/{a2['id']}/vote", json={"value": 5})
    data = qa["other_c"].get(f"/api/questions/{qa['q']['id']}").json
    assert data["question"]["best_answer_id"] == a2["id"]
    assert data["answers"][0]["id"] == a2["id"] and data["answers"][0]["is_best"]
    assert data["vote_values"] == [1, -1]
    assert qa["author_c"].get(f"/api/questions/{qa['q']['id']}").json["vote_values"] == [5, -1]


def test_profile_counts_schemes_per_topic(qa):
    qa["author_c"].put(f"/api/answers/{qa['a']['id']}/vote", json={"value": 5})
    topics = qa["other_c"].get(f"/api/users/{qa['answerer']['username']}").json["topics"]
    assert topics[0]["schemes"] == 1 and topics[0]["points"] == 5


def test_db_check_constraint_enforces_rule(app, qa):
    """Даже в обход API БД не пропустит +3 от автора или +5 от постороннего."""
    from app.db import session_scope

    async def insert(voter_id, value, is_author):
        async with session_scope() as s:
            await s.execute(text(
                "INSERT INTO votes (answer_id, voter_id, value, is_author_vote) "
                "VALUES (:a, :v, :val, :au)"), dict(a=qa["a"]["id"], v=voter_id, val=value, au=is_author))

    with app.app_context():
        for voter, value, is_author in [(qa["author"]["id"], 3, True), (qa["other"]["id"], 5, False)]:
            with pytest.raises(IntegrityError):
                asyncio.run(insert(voter, value, is_author))
