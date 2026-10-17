"""新增素材来源快照与视频迁移任务

Revision ID: 6c4d9140f96b
Revises: 0014b0f63f70
Create Date: 2026-10-17 19:17:50.957598

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c4d9140f96b'
down_revision: Union[str, None] = '0014b0f63f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 已审核：仅新增来源结构；历史数据由独立试跑工具回填。
    op.create_table('video_export_jobs',
    sa.Column('id', sa.String(length=64), nullable=False, comment='导出任务编号'),
    sa.Column('workspace_id', sa.Integer(), nullable=False, comment='所属工作区'),
    sa.Column('status', sa.String(length=32), nullable=False, comment='排队、执行、完成、失败或过期'),
    sa.Column('selection_json', sa.Text(), nullable=False, comment='请求时冻结的视频编号'),
    sa.Column('result_json', sa.Text(), nullable=True, comment='成功数量及逐项错误报告'),
    sa.Column('object_key', sa.String(length=512), nullable=True, comment='导出包对象存储键'),
    sa.Column('filename', sa.String(length=128), nullable=True, comment='下载文件名'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
    sa.Column('expires_at', sa.DateTime(), nullable=True, comment='导出文件过期时间'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    comment='视频后台导出任务'
    )
    with op.batch_alter_table('video_export_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_video_export_jobs_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('media_provenance',
    sa.Column('id', sa.Integer(), nullable=False, comment='来源编号'),
    sa.Column('workspace_id', sa.Integer(), nullable=True, comment='所属工作区'),
    sa.Column('photo_id', sa.Integer(), nullable=True, comment='所属图片，与视频互斥'),
    sa.Column('video_id', sa.Integer(), nullable=True, comment='所属视频，与图片互斥'),
    sa.Column('source_type', sa.String(length=32), nullable=False, comment='上传、导入、采集、截图或历史未知'),
    sa.Column('actor_name', sa.String(length=128), nullable=True, comment='入库人名称快照'),
    sa.Column('site_name', sa.String(length=128), nullable=True, comment='站点名称快照'),
    sa.Column('category_path', sa.String(length=1024), nullable=True, comment='分类路径快照'),
    sa.Column('record_method', sa.String(length=32), nullable=False, comment='实时记录或历史回填'),
    sa.Column('imported_at', sa.DateTime(), nullable=False, comment='本次正式入库时间'),
    sa.Column('snapshot_json', sa.Text(), nullable=False, comment='已校验脱敏的来源详情及原始上游快照'),
    sa.CheckConstraint('(photo_id IS NOT NULL AND video_id IS NULL) OR (photo_id IS NULL AND video_id IS NOT NULL)', name='ck_provenance_one_media'),
    sa.ForeignKeyConstraint(['photo_id'], ['gallery_photos.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['video_id'], ['video_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('photo_id'),
    sa.UniqueConstraint('video_id'),
    comment='正式素材首次入库来源'
    )
    with op.batch_alter_table('media_provenance', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_media_provenance_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('telegram_provenance',
    sa.Column('id', sa.Integer(), nullable=False, comment='平台快照编号'),
    sa.Column('provenance_id', sa.Integer(), nullable=False, comment='所属正式来源'),
    sa.Column('snapshot_json', sa.Text(), nullable=False, comment='会话、话题、消息、发送形式、标签及文案摘要'),
    sa.ForeignKeyConstraint(['provenance_id'], ['media_provenance.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provenance_id'),
    comment='Telegram来源快照'
    )
    with op.batch_alter_table('acquisition_import_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Integer(), nullable=True, comment='入库操作人'))
        batch_op.add_column(sa.Column('actor_name', sa.String(length=128), nullable=True, comment='操作人名称快照'))
        batch_op.create_foreign_key('fk_acquisition_import_batches_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('acquisition_run_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_snapshot_json', sa.Text(), nullable=True, comment='采集时冻结的公开来源快照'))

    with op.batch_alter_table('gallery_photos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Integer(), nullable=True, comment='入库操作人'))
        batch_op.add_column(sa.Column('actor_name', sa.String(length=128), nullable=True, comment='操作人名称快照'))
        batch_op.create_foreign_key('fk_gallery_photos_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Integer(), nullable=True, comment='入库操作人'))
        batch_op.add_column(sa.Column('actor_name', sa.String(length=128), nullable=True, comment='操作人名称快照'))
        batch_op.add_column(sa.Column('result_json', sa.Text(), nullable=True, comment='后台任务逐项结果报告'))
        batch_op.create_foreign_key('fk_tasks_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('video_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Integer(), nullable=True, comment='入库操作人'))
        batch_op.add_column(sa.Column('actor_name', sa.String(length=128), nullable=True, comment='操作人名称快照'))
        batch_op.add_column(sa.Column('content_sha256', sa.String(length=64), nullable=True, comment='当前存储文件内容哈希'))
        batch_op.create_index(batch_op.f('ix_video_items_content_sha256'), ['content_sha256'], unique=False)
        batch_op.create_foreign_key('fk_video_items_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('video_upload_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.Integer(), nullable=True, comment='入库操作人'))
        batch_op.add_column(sa.Column('actor_name', sa.String(length=128), nullable=True, comment='操作人名称快照'))
        batch_op.create_foreign_key('fk_video_upload_sessions_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL')

    # 迁移结束。


def downgrade() -> None:
    # 已审核：仅新增来源结构；历史数据由独立试跑工具回填。
    with op.batch_alter_table('video_upload_sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_video_upload_sessions_created_by', type_='foreignkey')
        batch_op.drop_column('actor_name')
        batch_op.drop_column('created_by')

    with op.batch_alter_table('video_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_video_items_created_by', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_video_items_content_sha256'))
        batch_op.drop_column('content_sha256')
        batch_op.drop_column('actor_name')
        batch_op.drop_column('created_by')

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tasks_created_by', type_='foreignkey')
        batch_op.drop_column('result_json')
        batch_op.drop_column('actor_name')
        batch_op.drop_column('created_by')

    with op.batch_alter_table('gallery_photos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_gallery_photos_created_by', type_='foreignkey')
        batch_op.drop_column('actor_name')
        batch_op.drop_column('created_by')

    with op.batch_alter_table('acquisition_run_items', schema=None) as batch_op:
        batch_op.drop_column('source_snapshot_json')

    with op.batch_alter_table('acquisition_import_batches', schema=None) as batch_op:
        batch_op.drop_constraint('fk_acquisition_import_batches_created_by', type_='foreignkey')
        batch_op.drop_column('actor_name')
        batch_op.drop_column('created_by')

    op.drop_table('telegram_provenance')
    with op.batch_alter_table('media_provenance', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_media_provenance_workspace_id'))

    op.drop_table('media_provenance')
    with op.batch_alter_table('video_export_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_video_export_jobs_workspace_id'))

    op.drop_table('video_export_jobs')
    # 迁移结束。
