"""Хэллоуинский ивент выключен по умолчанию, итоги закрывает админ.

Строка settings['halloween'] могла быть создана старым дефолтом (enabled=true
с датами 2026-10-01…2026-11-02) при первом тапе по рейду или сохранении настроек.
Сохранённое значение перекрывает новый дефолт, поэтому выключаем ровно тот случай,
когда в базе лежит нетронутый старый дефолт.

Revision ID: 0017_halloween_admin_close
Revises: 0016_halloween_raid_history
"""
from alembic import op

revision = "0017_halloween_admin_close"
down_revision = "0016_halloween_raid_history"
branch_labels = None
depends_on = None

LEGACY_START = "2026-10-01T00:00:00+00:00"
LEGACY_END = "2026-11-02T00:00:00+00:00"


def upgrade() -> None:
    op.execute(
        """
        UPDATE settings
           SET value = jsonb_set(value, '{enabled}', 'false'::jsonb)
                                     || jsonb_build_object('results_closed', false)
         WHERE key = 'halloween'
           AND value->>'enabled' = 'true'
           AND value->>'start_at' = '2026-10-01T00:00:00+00:00'
           AND value->>'end_at' = '2026-11-02T00:00:00+00:00'
        """
    )


def downgrade() -> None:
    # Обратно включать ивент не нужно: старый дефолт был ошибкой конфигурации.
    pass
