"""add outbound_ready and inbound_ready columns to agents

Revision ID: ob1a2b3c4d5e
Revises: dg3f1a2b3c4d
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ob1a2b3c4d5e'
down_revision: Union[str, None] = 'dg3f1a2b3c4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('outbound_ready', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('agents', sa.Column('inbound_ready', sa.Boolean(), server_default='1', nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'inbound_ready')
    op.drop_column('agents', 'outbound_ready')
