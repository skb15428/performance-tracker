"""saved learning progress, background checks, big-picture notes

Revision ID: b7c4e2d18a36
Revises: e3a1c7d95b20
Create Date: 2026-11-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e2d18a36'
down_revision: Union[str, Sequence[str], None] = 'e3a1c7d95b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('roadmap_items', sa.Column('background', sa.JSON(), nullable=True))
    op.add_column('study_topics', sa.Column('understood', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('study_topics', sa.Column('resume_note', sa.Text(), server_default='', nullable=False))
    with op.batch_alter_table('topic_notes') as batch:
        batch.add_column(sa.Column('roadmap_item_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('topic_notes_roadmap_item_id_fkey', 'roadmap_items', ['roadmap_item_id'], ['id'],
                                 ondelete='SET NULL')
        batch.create_unique_constraint('topic_notes_roadmap_item_id_key', ['roadmap_item_id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('topic_notes') as batch:
        batch.drop_constraint('topic_notes_roadmap_item_id_key', type_='unique')
        batch.drop_constraint('topic_notes_roadmap_item_id_fkey', type_='foreignkey')
        batch.drop_column('roadmap_item_id')
    op.drop_column('study_topics', 'resume_note')
    op.drop_column('study_topics', 'understood')
    op.drop_column('roadmap_items', 'background')
