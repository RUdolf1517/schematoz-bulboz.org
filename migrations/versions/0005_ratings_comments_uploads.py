"""ratings comments uploads

Revision ID: 0005_ratings
Revises: 0004_login_keys
Create Date: 2026-09-26 19:06:57.132886
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0005_ratings'
down_revision: Union[str, None] = '0004_login_keys'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE report_target ADD VALUE IF NOT EXISTS 'comment'")
    op.create_table('uploads',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('width', sa.Integer(), nullable=False),
    sa.Column('height', sa.Integer(), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_uploads_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_uploads')),
    sa.UniqueConstraint('name', name=op.f('uq_uploads_name'))
    )
    op.create_index(op.f('ix_uploads_user_id'), 'uploads', ['user_id'], unique=False)
    op.create_table('question_votes',
    sa.Column('question_id', sa.BigInteger(), nullable=False),
    sa.Column('voter_id', sa.BigInteger(), nullable=False),
    sa.Column('value', sa.SmallInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('value IN (1, -1)', name=op.f('ck_question_votes_value_pm1')),
    sa.ForeignKeyConstraint(['question_id'], ['questions.id'], name=op.f('fk_question_votes_question_id_questions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['voter_id'], ['users.id'], name=op.f('fk_question_votes_voter_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('question_id', 'voter_id', name=op.f('pk_question_votes'))
    )
    op.create_table('comments',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('answer_id', sa.BigInteger(), nullable=False),
    sa.Column('question_id', sa.BigInteger(), nullable=False),
    sa.Column('author_id', sa.BigInteger(), nullable=False),
    sa.Column('body', sa.String(length=200), nullable=False),
    sa.Column('status', postgresql.ENUM(name='content_status', create_type=False), server_default='active', nullable=False),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(body) BETWEEN 1 AND 200', name=op.f('ck_comments_body_len')),
    sa.ForeignKeyConstraint(['answer_id'], ['answers.id'], name=op.f('fk_comments_answer_id_answers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_comments_author_id_users')),
    sa.ForeignKeyConstraint(['question_id'], ['questions.id'], name=op.f('fk_comments_question_id_questions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comments'))
    )
    op.create_index('ix_comments_answer', 'comments', ['answer_id', 'id'], unique=False)
    op.create_index(op.f('ix_comments_author_id'), 'comments', ['author_id'], unique=False)
    op.create_index(op.f('ix_comments_question_id'), 'comments', ['question_id'], unique=False)
    op.add_column('answers', sa.Column('comments_count', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('questions', sa.Column('votes_score', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('questions', sa.Column('comments_count', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('questions', sa.Column('rating', sa.Float(), server_default='0', nullable=False))
    op.add_column('questions', sa.Column('cover_url', sa.String(length=128), nullable=True))
    op.add_column('users', sa.Column('rating', sa.Float(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('rating_tier', sa.SmallInteger(), server_default='0', nullable=False))
    op.create_index("ix_users_rating_rank", "users", [sa.text("rating_tier DESC"), sa.text("rating DESC")])
    op.execute("UPDATE users SET rating_tier = 2 WHERE id IN (SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE r.code = 'admin')")
    op.execute("UPDATE users SET rating_tier = 1 WHERE rating_tier = 0 AND id IN (SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE r.code = 'moderator')")


def downgrade() -> None:
    # значение 'comment' в enum report_target остаётся: PostgreSQL не умеет удалять значения enum
    op.execute("DELETE FROM reports WHERE target_type = 'comment'")
    op.drop_index("ix_users_rating_rank", table_name="users")
    op.drop_column('users', 'rating_tier')
    op.drop_column('users', 'rating')
    op.drop_column('questions', 'cover_url')
    op.drop_column('questions', 'rating')
    op.drop_column('questions', 'comments_count')
    op.drop_column('questions', 'votes_score')
    op.drop_column('answers', 'comments_count')
    op.drop_index(op.f('ix_comments_question_id'), table_name='comments')
    op.drop_index(op.f('ix_comments_author_id'), table_name='comments')
    op.drop_index('ix_comments_answer', table_name='comments')
    op.drop_table('comments')
    op.drop_table('question_votes')
    op.drop_index(op.f('ix_uploads_user_id'), table_name='uploads')
    op.drop_table('uploads')
    # ### end Alembic commands ###
