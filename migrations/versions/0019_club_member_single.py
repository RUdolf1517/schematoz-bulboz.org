"""Один аккаунт — один кооператив: уникальный индекс на club_members.user_id.

Revision ID: 0019_club_member_single
Revises: 0018_clubs
Create Date: 2026-10-06 19:45:00.000000

Раньше «одна учётка — один клуб» держалось только на проверке в сервисе, поэтому
двойное нажатие «Основать» (гонка двух запросов) или одобрение заявки уже ушедшего
в другой клуб игрока заводили его сразу в два клуба. Чиним инвариантом в БД.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision = '0019_club_member_single'
down_revision: Union[str, None] = '0018_clubs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Дубли могли появиться до инварианта: оставляем клуб, где игрок глава/зам и который жив,
    # затем выравниваем денормализованный счётчик участников.
    op.execute(sa.text("""
        WITH ranked AS (
            SELECT cm.club_id, cm.user_id,
                   row_number() OVER (
                       PARTITION BY cm.user_id
                       ORDER BY (c.status = 'active') DESC,
                                CASE cm.role WHEN 'leader' THEN 0 WHEN 'deputy' THEN 1 ELSE 2 END,
                                cm.joined_at DESC
                   ) AS rn
            FROM club_members cm
            JOIN clubs c ON c.id = cm.club_id
        )
        DELETE FROM club_members cm
        USING ranked r
        WHERE cm.club_id = r.club_id AND cm.user_id = r.user_id AND r.rn > 1
    """))
    op.execute(sa.text("""
        UPDATE clubs SET members = (SELECT count(*) FROM club_members cm WHERE cm.club_id = clubs.id)
    """))
    op.drop_index('ix_club_members_user', table_name='club_members')
    op.create_index('uq_club_members_user', 'club_members', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_club_members_user', table_name='club_members')
    op.create_index('ix_club_members_user', 'club_members', ['user_id'], unique=False)
