"""make order product_id nullable

Revision ID: ea950e4c057e
Revises: 0a2e4adfe3d2
Create Date: 2026-02-12 22:42:59.357309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea950e4c057e'
down_revision: Union[str, Sequence[str], None] = '0a2e4adfe3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make orders.product_id nullable for unmatched orders."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.alter_column('product_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade() -> None:
    """Restore orders.product_id as NOT NULL."""
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.alter_column('product_id',
               existing_type=sa.INTEGER(),
               nullable=False)
