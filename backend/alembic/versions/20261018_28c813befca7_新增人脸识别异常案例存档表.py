"""新增人脸识别异常案例存档表

版本：28c813befca7
前置版本：c0bfc2bfbed1
创建时间：2026-10-18 20:06:11

仅新增案例表及索引，不回填或修改现有业务数据。

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic 迁移链标识。
revision: str = '28c813befca7'
down_revision: Union[str, None] = 'c0bfc2bfbed1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增独立案例表，源图和人物删除后仅解除外键关联。
    op.create_table('face_recognition_cases',
    sa.Column('id', sa.String(length=32), nullable=False, comment='案例编号'),
    sa.Column('workspace_id', sa.Integer(), nullable=False, comment='所属工作区'),
    sa.Column('source_photo_id', sa.Integer(), nullable=True, comment='仍存在的源图库图片编号，删除图片后置空'),
    sa.Column('source_face_id', sa.Integer(), nullable=False, comment='原人脸编号快照，不随重识别删除'),
    sa.Column('correct_person_id', sa.Integer(), nullable=True, comment='仍存在的正确人物编号，删除人物后置空'),
    sa.Column('correct_person_name', sa.String(length=256), nullable=False, comment='正确人物名称快照'),
    sa.Column('issue_type', sa.String(length=32), nullable=False, comment='人工选择的异常类型'),
    sa.Column('notes', sa.Text(), nullable=False, comment='人工备注'),
    sa.Column('recognition_key', sa.String(length=64), nullable=False, comment='识别事件指纹，同工作区内唯一'),
    sa.Column('embedding_version', sa.String(length=64), nullable=True, comment='原识别向量版本'),
    sa.Column('object_key', sa.String(length=512), nullable=False, comment='案例独立存档原图对象键'),
    sa.Column('snapshot_json', sa.Text(), nullable=False, comment='版本化的图片、人脸、人物及记录时样本清单快照'),
    sa.Column('created_by', sa.Integer(), nullable=True, comment='记录人编号，删除用户后置空'),
    sa.Column('actor_name', sa.String(length=128), nullable=False, comment='记录人名称快照'),
    sa.Column('status', sa.String(length=16), nullable=False, comment='案例状态，active 为正常，deleting 为待重试清理'),
    sa.Column('cleanup_error', sa.Text(), nullable=True, comment='素材清理失败原因'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='案例记录时间'),
    sa.Column('updated_at', sa.DateTime(), nullable=False, comment='备注或清理状态更新时间'),
    sa.ForeignKeyConstraint(['correct_person_id'], ['persons.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_photo_id'], ['gallery_photos.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('object_key'),
    sa.UniqueConstraint('workspace_id', 'recognition_key', name='uq_face_case_recognition'),
    comment='人工标注的人脸识别异常案例与独立素材快照'
    )
    with op.batch_alter_table('face_recognition_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_correct_person_id'), ['correct_person_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_embedding_version'), ['embedding_version'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_issue_type'), ['issue_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_source_photo_id'), ['source_photo_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_recognition_cases_workspace_id'), ['workspace_id'], unique=False)



def downgrade() -> None:
    # 回退仅移除本迁移新增的索引和案例表。
    with op.batch_alter_table('face_recognition_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_source_photo_id'))
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_issue_type'))
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_embedding_version'))
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_created_at'))
        batch_op.drop_index(batch_op.f('ix_face_recognition_cases_correct_person_id'))

    op.drop_table('face_recognition_cases')
