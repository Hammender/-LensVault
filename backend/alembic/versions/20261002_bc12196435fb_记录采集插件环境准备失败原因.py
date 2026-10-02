"""记录采集插件环境准备失败原因

Revision ID: bc12196435fb
Revises: 19a44fe179ff
Create Date: 2026-10-02 16:49:28.584288+08:00

为 acquisition_plugin_versions 增加可空 last_error，保存最近一次环境准备失败原因。
存量行保持为空；不影响已启用插件或采集历史。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc12196435fb'
down_revision: Union[str, None] = '19a44fe179ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('acquisition_plugin_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_error', sa.Text(), nullable=True, comment='最近一次环境准备失败原因'))


def downgrade() -> None:
    with op.batch_alter_table('acquisition_plugin_versions', schema=None) as batch_op:
        batch_op.drop_column('last_error')
