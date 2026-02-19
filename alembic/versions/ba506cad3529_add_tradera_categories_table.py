"""add tradera_categories table

Revision ID: ba506cad3529
Revises: c364b1dcc103
Create Date: 2026-02-19 21:10:35.882911

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba506cad3529'
down_revision: Union[str, Sequence[str], None] = 'c364b1dcc103'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('tradera_categories',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tradera_id', sa.Integer(), nullable=False),
    sa.Column('parent_tradera_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('path', sa.String(), nullable=False),
    sa.Column('depth', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('synced_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tradera_categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tradera_categories_tradera_id'), ['tradera_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tradera_categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tradera_categories_tradera_id'))

    op.drop_table('tradera_categories')
