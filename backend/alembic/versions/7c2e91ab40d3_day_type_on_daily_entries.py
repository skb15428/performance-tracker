"""flexible days, time logs, frozen weeks, job search, proof links, sign-in lockout

Revision ID: 7c2e91ab40d3
Revises: 4277249b3fd5
Create Date: 2026-11-01 02:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2e91ab40d3'
down_revision: Union[str, Sequence[str], None] = '4277249b3fd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GUID = fastapi_users_db_sqlalchemy.generics.GUID()


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('daily_entries', sa.Column('day_type', sa.String(length=10), nullable=True))
    op.add_column('daily_entries', sa.Column('goal_day_types', sa.JSON(), nullable=True))
    op.add_column('goal_metrics', sa.Column('source', sa.String(length=20), nullable=True))
    op.add_column('roadmap_items', sa.Column('proof_links', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('users', sa.Column('last_morning_on', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('last_weekly_nudge_on', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('failed_logins', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('calendar_token', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_users_calendar_token'), 'users', ['calendar_token'], unique=False)
    op.create_table('time_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', GUID, nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('goal_id', sa.Integer(), nullable=False),
    sa.Column('roadmap_item_id', sa.Integer(), nullable=True),
    sa.Column('plan_item_id', sa.Integer(), nullable=True),
    sa.Column('minutes', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plan_item_id'], ['plan_items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['roadmap_item_id'], ['roadmap_items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_time_logs_day'), 'time_logs', ['day'], unique=False)
    op.create_index(op.f('ix_time_logs_goal_id'), 'time_logs', ['goal_id'], unique=False)
    op.create_index(op.f('ix_time_logs_plan_item_id'), 'time_logs', ['plan_item_id'], unique=False)
    op.create_index(op.f('ix_time_logs_user_id'), 'time_logs', ['user_id'], unique=False)
    op.create_table('week_plans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('goal_id', sa.Integer(), nullable=False),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('minutes', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('goal_id', 'week_start')
    )
    op.create_index(op.f('ix_week_plans_goal_id'), 'week_plans', ['goal_id'], unique=False)
    op.create_table('job_applications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', GUID, nullable=False),
    sa.Column('company', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=200), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('referral', sa.String(length=200), nullable=False),
    sa.Column('stage', sa.String(length=12), nullable=False),
    sa.Column('reached_final', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('applied_on', sa.Date(), nullable=True),
    sa.Column('next_step', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_applications_user_id'), 'job_applications', ['user_id'], unique=False)
    op.create_table('app_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_app_events_created_at'), 'app_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_app_events_kind'), 'app_events', ['kind'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('app_events')
    op.drop_table('job_applications')
    op.drop_table('week_plans')
    op.drop_table('time_logs')
    op.drop_index(op.f('ix_users_calendar_token'), table_name='users')
    op.drop_column('users', 'calendar_token')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_logins')
    op.drop_column('users', 'last_weekly_nudge_on')
    op.drop_column('users', 'last_morning_on')
    op.drop_column('roadmap_items', 'proof_links')
    op.drop_column('goal_metrics', 'source')
    op.drop_column('daily_entries', 'goal_day_types')
    op.drop_column('daily_entries', 'day_type')
