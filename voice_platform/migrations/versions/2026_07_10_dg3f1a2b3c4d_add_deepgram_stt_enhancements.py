"""add deepgram stt enhancements and analysis_provider columns

Revision ID: dg3f1a2b3c4d
Revises: 74691b457118
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'dg3f1a2b3c4d'
down_revision: Union[str, None] = '74691b457118'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('stt_smart_format', sa.Boolean(), server_default='1', nullable=True))
    op.add_column('agents', sa.Column('stt_diarize', sa.Boolean(), server_default='1', nullable=True))
    op.add_column('agents', sa.Column('stt_filter_filler_words', sa.Boolean(), server_default='0', nullable=True))
    op.add_column('agents', sa.Column('analysis_provider', sa.String(20), server_default='auto', nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'analysis_provider')
    op.drop_column('agents', 'stt_filter_filler_words')
    op.drop_column('agents', 'stt_diarize')
    op.drop_column('agents', 'stt_smart_format')
