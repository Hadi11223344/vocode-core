"""raise agent max_tokens default to 2048

Revision ID: 74691b457118
Revises: a1b2c3d4e5f6
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '74691b457118'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'agents',
        'max_tokens',
        existing_type=sa.Integer(),
        server_default='2048',
    )


def downgrade() -> None:
    op.alter_column(
        'agents',
        'max_tokens',
        existing_type=sa.Integer(),
        server_default='256',
    )
