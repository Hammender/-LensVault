"""新增视频截图来源快照。

仅为采集素材新增可空 JSON 文本列，普通素材保持空值，无需回填。
截图保存原视频和来源快照，展示图库结构不变。回退会移除截图快照字段。

Revision ID: 0014b0f63f70
Revises: bc12196435fb
Create Date: 2026-10-04 23:16:53.302951+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014b0f63f70'
down_revision: Union[str, None] = 'bc12196435fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('acquisition_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('capture_metadata_json', sa.Text(), nullable=True, comment='视频截图来源快照：原视频、帧时间及采集来源；普通素材为空'))



def downgrade() -> None:
    with op.batch_alter_table('acquisition_assets', schema=None) as batch_op:
        batch_op.drop_column('capture_metadata_json')
