"""新增采集插件版本与账号配置

Revision ID: 19a44fe179ff
Revises: 364bf17881ef
Create Date: 2026-09-26 13:53:25.268333

新增不可变插件版本表、工作区加密凭据表、运行凭据关联及通用来源元数据。
现有运行的凭据关联留空；不迁移或删除原有采集历史。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19a44fe179ff'
down_revision: Union[str, None] = '364bf17881ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('acquisition_plugin_versions',
    sa.Column('id', sa.Integer(), nullable=False, comment='主键标识'),
    sa.Column('script_key', sa.String(length=128), nullable=False, comment='插件脚本稳定标识'),
    sa.Column('version', sa.String(length=64), nullable=False, comment='插件版本号'),
    sa.Column('manifest_json', sa.Text(), nullable=False, comment='插件清单快照'),
    sa.Column('package_sha256', sa.String(length=64), nullable=False, comment='原始上传包的 SHA256'),
    sa.Column('status', sa.String(length=32), nullable=False, comment='上传、就绪或失败状态'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='记录创建时间（上海时区无时区值）'),
    sa.ForeignKeyConstraint(['script_key'], ['acquisition_scripts.key'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('script_key', 'version', name='uq_acquisition_plugin_version'),
    comment='已上传采集插件的不可变版本及准备状态'
    )
    with op.batch_alter_table('acquisition_plugin_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_acquisition_plugin_versions_script_key'), ['script_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_acquisition_plugin_versions_status'), ['status'], unique=False)

    op.create_table('acquisition_plugin_credentials',
    sa.Column('id', sa.Integer(), nullable=False, comment='主键标识'),
    sa.Column('workspace_id', sa.Integer(), nullable=False, comment='所属工作区'),
    sa.Column('script_key', sa.String(length=128), nullable=False, comment='所属采集插件'),
    sa.Column('name', sa.String(length=128), nullable=False, comment='账号配置名称'),
    sa.Column('encrypted_json', sa.Text(), nullable=False, comment='加密后的插件凭据'),
    sa.Column('status', sa.String(length=32), nullable=False, comment='连接测试状态'),
    sa.Column('last_tested_at', sa.DateTime(), nullable=True, comment='最近测试时间'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='记录创建时间（上海时区无时区值）'),
    sa.Column('updated_at', sa.DateTime(), nullable=False, comment='记录最后更新时间（上海时区无时区值）'),
    sa.ForeignKeyConstraint(['script_key'], ['acquisition_scripts.key'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'script_key', 'name', name='uq_acquisition_plugin_credential'),
    comment='工作区内按插件隔离的加密登录凭据'
    )
    with op.batch_alter_table('acquisition_plugin_credentials', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_acquisition_plugin_credentials_script_key'), ['script_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_acquisition_plugin_credentials_workspace_id'), ['workspace_id'], unique=False)

    with op.batch_alter_table('acquisition_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('credential_id', sa.Integer(), nullable=True, comment='本次采集使用的工作区账号配置'))
        batch_op.create_foreign_key('fk_acquisition_runs_credential_id', 'acquisition_plugin_credentials', ['credential_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('acquisition_source_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_json', sa.Text(), nullable=True, comment='来源文案、标签和发布时间的结构化快照'))



def downgrade() -> None:
    with op.batch_alter_table('acquisition_source_items', schema=None) as batch_op:
        batch_op.drop_column('metadata_json')

    with op.batch_alter_table('acquisition_runs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_acquisition_runs_credential_id', type_='foreignkey')
        batch_op.drop_column('credential_id')

    with op.batch_alter_table('acquisition_plugin_credentials', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_acquisition_plugin_credentials_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_acquisition_plugin_credentials_script_key'))

    op.drop_table('acquisition_plugin_credentials')
    with op.batch_alter_table('acquisition_plugin_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_acquisition_plugin_versions_status'))
        batch_op.drop_index(batch_op.f('ix_acquisition_plugin_versions_script_key'))

    op.drop_table('acquisition_plugin_versions')
