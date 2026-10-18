"""扩展识别异常人工结论与排除人物

新增人工结论类型及排除人物快照，旧记录默认按库中人物处理，不改写旧快照。
SQLite 通过批处理重建表，保留原有数据、索引和约束。
回退会移除新增的结论及排除人物字段，应先处理这些新增标注。

Revision ID: cd66950508ae
Revises: 28c813befca7
Create Date: 2026-10-18 20:41:47.297761

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic 迁移链标识。
revision: str = 'cd66950508ae'
down_revision: Union[str, None] = '28c813befca7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 服务端默认值使旧案例保留原来的库中人物语义。
    with op.batch_alter_table('face_recognition_cases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('answer_type', sa.String(length=32), server_default='known_person', nullable=False, comment='人工结论类型：库中人物、库外人物或仅排除指定人物'))
        batch_op.add_column(sa.Column('excluded_person_id', sa.Integer(), nullable=True, comment='明确排除的人物编号，删除人物后置空'))
        batch_op.add_column(sa.Column('excluded_person_name', sa.String(length=256), nullable=True, comment='明确排除的人物名称快照'))
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_answer_type'), ['answer_type'], unique=False)
        batch_op.create_foreign_key('fk_face_cases_excluded_person', 'persons', ['excluded_person_id'], ['id'], ondelete='SET NULL')



def downgrade() -> None:
    # 仅撤销本次新增的约束、索引和列。
    with op.batch_alter_table('face_recognition_cases', schema=None) as batch_op:
        batch_op.drop_constraint('fk_face_cases_excluded_person', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_answer_type'))
        batch_op.drop_column('excluded_person_name')
        batch_op.drop_column('excluded_person_id')
        batch_op.drop_column('answer_type')

