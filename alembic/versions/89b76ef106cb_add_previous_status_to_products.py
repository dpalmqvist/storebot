"""add previous_status to products

Revision ID: 89b76ef106cb
Revises: ea950e4c057e
Create Date: 2026-02-13 12:59:40.783003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89b76ef106cb'
down_revision: Union[str, Sequence[str], None] = 'ea950e4c057e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('previous_status', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('previous_status')
