"""add api_usage table

Revision ID: c364b1dcc103
Revises: 89b76ef106cb
Create Date: 2026-02-15 20:39:52.173656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c364b1dcc103'
down_revision: Union[str, Sequence[str], None] = '89b76ef106cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('api_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.String(), nullable=True),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('cache_creation_input_tokens', sa.Integer(), nullable=False),
    sa.Column('cache_read_input_tokens', sa.Integer(), nullable=False),
    sa.Column('tool_calls', sa.Integer(), nullable=False),
    sa.Column('estimated_cost_sek', sa.Numeric(10, 4), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('api_usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_api_usage_chat_id'), ['chat_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_api_usage_created_at'), ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('api_usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_usage_created_at'))
        batch_op.drop_index(batch_op.f('ix_api_usage_chat_id'))

    op.drop_table('api_usage')
