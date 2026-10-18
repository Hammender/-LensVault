"""新增采集素材首次来源快照

Revision ID: c0bfc2bfbed1
Revises: 6c4d9140f96b
Create Date: 2026-10-18 10:53:18.315664

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0bfc2bfbed1'
down_revision: Union[str, None] = '6c4d9140f96b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 存量可空，下次采集命中或人工回填时才有值。
    with op.batch_alter_table('acquisition_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_snapshot_json', sa.Text(), nullable=True, comment='首次采集来源快照；分类或站点删除后仍可追溯'))


def downgrade() -> None:
    # 降级会丢失素材侧的来源快照；正式来源表 media_provenance 不受影响。
    with op.batch_alter_table('acquisition_assets', schema=None) as batch_op:
        batch_op.drop_column('source_snapshot_json')
