"""Permanent Halloween mutations, including records created under the old expiry rule."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import halloween


def test_legacy_expired_mutations_remain_visible_and_deduplicate():
    kombucha = SimpleNamespace(halloween_mutations=[
        {
            "code": "halloween_ghost",
            "at": "2026-10-01T12:00:00+00:00",
            "expires_at": "2026-10-04T12:00:00+00:00",
        },
        {
            "code": "halloween_ghost",
            "at": "2026-10-04T12:00:00+00:00",
            "expires_at": "2026-10-07T12:00:00+00:00",
        },
    ])

    mutations = halloween.active_mutations(
        kombucha, at=datetime(2026, 12, 1, tzinfo=timezone.utc)
    )

    assert [mutation["code"] for mutation in mutations] == ["halloween_ghost"]
    assert mutations[0]["rarity_title"] == "Постоянная хэллоуинская"
    assert "expires_at" not in mutations[0]


def test_new_halloween_mutations_are_permanent_and_not_duplicated():
    at = datetime(2026, 10, 31, tzinfo=timezone.utc)
    kombucha = SimpleNamespace(id=1, user_id=2, halloween_mutations=[])
    session = SimpleNamespace(add=lambda _event: None)

    awards = [
        halloween.add_temp_mutation(session, kombucha, at=at, force=True)
        for _ in halloween.TEMP_MUTATIONS
    ]

    assert all(award is not None and "expires_at" not in award for award in awards)
    assert {award["code"] for award in awards} == set(halloween.TEMP_MUTATIONS)
    assert all("expires_at" not in entry for entry in kombucha.halloween_mutations)
    assert len(halloween.active_mutations(kombucha, at + timedelta(days=365))) == len(halloween.TEMP_MUTATIONS)
    assert halloween.add_temp_mutation(session, kombucha, at=at, force=True) is None
