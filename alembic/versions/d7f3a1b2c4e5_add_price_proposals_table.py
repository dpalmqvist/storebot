"""add price_proposals table

Revision ID: d7f3a1b2c4e5
Revises: ba506cad3529
Create Date: 2026-03-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7f3a1b2c4e5'
down_revision: Union[str, Sequence[str], None] = 'ba506cad3529'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('price_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('listing_id', sa.Integer(), nullable=False),
    sa.Column('proposal_type', sa.String(), nullable=False),
    sa.Column('current_price', sa.Float(), nullable=False),
    sa.Column('suggested_price', sa.Float(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(), nullable=False, server_default='pending'),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('executed_at', sa.DateTime(), nullable=True),
    sa.Column('execution_error', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['listing_id'], ['platform_listings.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('price_proposals', schema=None) as batch_op:
        batch_op.create_index('ix_price_proposals_listing_status', ['listing_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('price_proposals', schema=None) as batch_op:
        batch_op.drop_index('ix_price_proposals_listing_status')

    op.drop_table('price_proposals')
