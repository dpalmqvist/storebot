"""add feedback_left_at to orders

Revision ID: 0a2e4adfe3d2
Revises: d500fe688d0d
Create Date: 2026-02-12 21:41:53.366696

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a2e4adfe3d2'
down_revision: Union[str, Sequence[str], None] = 'd500fe688d0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('feedback_left_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('feedback_left_at')
