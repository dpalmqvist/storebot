"""add weight_grams tracking_number label_path

Revision ID: d500fe688d0d
Revises: 80dfa55ce86d
Create Date: 2026-02-12 20:12:08.649261

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd500fe688d0d'
down_revision: Union[str, Sequence[str], None] = '80dfa55ce86d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tracking_number', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('label_path', sa.String(), nullable=True))

    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('weight_grams', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('weight_grams')

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('label_path')
        batch_op.drop_column('tracking_number')
