"""add listing_snapshots table

Revision ID: 80dfa55ce86d
Revises: 8fcd3a05b7fe
Create Date: 2026-02-12 09:22:39.544401

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80dfa55ce86d'
down_revision: Union[str, Sequence[str], None] = '8fcd3a05b7fe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('listing_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('listing_id', sa.Integer(), nullable=False),
    sa.Column('views', sa.Integer(), nullable=False),
    sa.Column('watchers', sa.Integer(), nullable=False),
    sa.Column('bids', sa.Integer(), nullable=False),
    sa.Column('current_price', sa.Float(), nullable=True),
    sa.Column('snapshot_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['platform_listings.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('listing_snapshots')
