-- PictureShow 全量表设计
-- 本文件由 backend/app/tools/export_schema_sql.py 根据 ORM 元数据生成，请勿手工修改。
-- 生成命令：$env:PYTHONPATH='backend'; python -m app.tools.export_schema_sql
-- 适用数据库：SQLite；包含全部业务表、运行时迁移登记表、索引、外键、默认值及中文说明。

PRAGMA foreign_keys = ON;

-- 表名：acquisition_scripts
-- 表说明：可复用的图片采集脚本定义
-- 字段说明：
--   key：业务唯一键
--   name：名称
--   version：采集脚本版本号
--   page_format_key：采集页面格式标识
--   description：文字说明
--   parameter_schema_json：采集脚本参数定义，JSON 数组
--   enabled：是否启用
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_scripts (
	"key" VARCHAR(128) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	version VARCHAR(64) NOT NULL, 
	page_format_key VARCHAR(128) NOT NULL, 
	description TEXT, 
	parameter_schema_json TEXT NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY ("key")
);
CREATE INDEX ix_acquisition_scripts_enabled ON acquisition_scripts (enabled);
CREATE INDEX ix_acquisition_scripts_page_format_key ON acquisition_scripts (page_format_key);

-- 表名：users
-- 表说明：系统登录用户
-- 字段说明：
--   id：主键标识
--   username：登录用户名
--   display_name：界面展示名称
--   password_hash：密码哈希值，不保存明文密码
--   is_admin：是否为系统管理员
--   is_active：用户账号是否启用
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(128) NOT NULL, 
	display_name VARCHAR(128) NOT NULL, 
	password_hash VARCHAR(512) NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_users_is_active ON users (is_active);
CREATE INDEX ix_users_is_admin ON users (is_admin);
CREATE UNIQUE INDEX ix_users_username ON users (username);

-- 表名：workspaces
-- 表说明：数据隔离工作区
-- 字段说明：
--   id：主键标识
--   name：名称
--   kind：工作区类型：private（私有）或 shared（共享）
--   owner_user_id：工作区拥有者用户标识
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE workspaces (
	id INTEGER NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	owner_user_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE SET NULL
);
CREATE INDEX ix_workspaces_kind ON workspaces (kind);
CREATE INDEX ix_workspaces_name ON workspaces (name);
CREATE INDEX ix_workspaces_owner_user_id ON workspaces (owner_user_id);

-- 表名：acquisition_assets
-- 表说明：采集下载得到的候选图片资产
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   sha256：文件内容 SHA-256 摘要
--   filename：原始文件名
--   content_type：文件 MIME 类型
--   object_key：对象存储中的文件键
--   size_bytes：文件大小，单位为字节
--   width：媒体宽度，单位为像素
--   height：媒体高度，单位为像素
--   blur_score：人脸清晰度评分
--   perceptual_phash：采集图片感知哈希值
--   perceptual_dhash：采集图片差异哈希值
--   quality_score：图片质量评分
--   quality_warnings：图片质量告警，JSON 或文本
--   status：采集图片状态：pending_review、import_queued、importing、imported、import_failed、gallery_duplicate 或 rejected
--   error_message：失败或异常原因
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_assets (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	sha256 VARCHAR(64) NOT NULL, 
	filename VARCHAR(512) NOT NULL, 
	content_type VARCHAR(128), 
	object_key VARCHAR(512), 
	size_bytes BIGINT NOT NULL, 
	width INTEGER, 
	height INTEGER, 
	blur_score FLOAT, 
	perceptual_phash VARCHAR(32), 
	perceptual_dhash VARCHAR(32), 
	quality_score FLOAT, 
	quality_warnings TEXT, 
	status VARCHAR(32) NOT NULL, 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_asset_workspace_sha256 UNIQUE (workspace_id, sha256), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);
CREATE INDEX ix_acquisition_assets_perceptual_dhash ON acquisition_assets (perceptual_dhash);
CREATE INDEX ix_acquisition_assets_perceptual_phash ON acquisition_assets (perceptual_phash);
CREATE INDEX ix_acquisition_assets_sha256 ON acquisition_assets (sha256);
CREATE INDEX ix_acquisition_assets_status ON acquisition_assets (status);
CREATE INDEX ix_acquisition_assets_workspace_id ON acquisition_assets (workspace_id);

-- 表名：acquisition_export_jobs
-- 表说明：采集资产导出压缩包的异步任务
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   status：导出任务状态：pending、running、ready、downloaded、failed 或 expired
--   filters_json：导出任务筛选条件，JSON 对象
--   object_key：对象存储中的文件键
--   filename：原始文件名
--   item_count：导出任务包含的图片数量
--   missing_count：导出时缺失的图片数量
--   error_message：失败或异常原因
--   expires_at：导出文件过期时间
--   created_at：记录创建时间（上海时区无时区值）
--   completed_at：处理完成时间
--   downloaded_at：导出文件下载时间
CREATE TABLE acquisition_export_jobs (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	status VARCHAR(32) NOT NULL, 
	filters_json TEXT NOT NULL, 
	object_key VARCHAR(512), 
	filename VARCHAR(512), 
	item_count INTEGER NOT NULL, 
	missing_count INTEGER NOT NULL, 
	error_message TEXT, 
	expires_at DATETIME, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	downloaded_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);
CREATE INDEX ix_acquisition_export_jobs_expires_at ON acquisition_export_jobs (expires_at);
CREATE INDEX ix_acquisition_export_jobs_status ON acquisition_export_jobs (status);
CREATE INDEX ix_acquisition_export_jobs_workspace_id ON acquisition_export_jobs (workspace_id);

-- 表名：acquisition_import_batches
-- 表说明：审核通过的采集资产入库批次
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   status：导入批次状态：queued、running、completed、completed_with_errors 或 failed
--   total_count：本次处理项目总数
--   processed_count：已处理数量
--   imported_count：成功入库数量
--   duplicate_count：重复数量
--   failed_count：失败数量
--   error_message：失败或异常原因
--   started_at：处理开始时间
--   completed_at：处理完成时间
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_import_batches (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	status VARCHAR(32) NOT NULL, 
	total_count INTEGER NOT NULL, 
	processed_count INTEGER NOT NULL, 
	imported_count INTEGER NOT NULL, 
	duplicate_count INTEGER NOT NULL, 
	failed_count INTEGER NOT NULL, 
	error_message TEXT, 
	started_at DATETIME, 
	completed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_acquisition_import_batches_created_at ON acquisition_import_batches (created_at);
CREATE INDEX ix_acquisition_import_batches_status ON acquisition_import_batches (status);
CREATE INDEX ix_acquisition_import_batches_workspace_id ON acquisition_import_batches (workspace_id);

-- 表名：acquisition_sources
-- 表说明：图片采集站点来源配置
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   name：名称
--   adapter_key：采集来源适配器标识
--   base_url：采集来源基础地址
--   notes：备注说明
--   page_format_key：采集页面格式标识
--   enabled：是否启用
--   settings_json：采集来源配置，JSON 对象
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_sources (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	name VARCHAR(128) NOT NULL, 
	adapter_key VARCHAR(64) NOT NULL, 
	base_url VARCHAR(1024), 
	notes TEXT, 
	page_format_key VARCHAR(128), 
	enabled BOOLEAN NOT NULL, 
	settings_json TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_source_workspace_name UNIQUE (workspace_id, name), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_acquisition_sources_adapter_key ON acquisition_sources (adapter_key);
CREATE INDEX ix_acquisition_sources_enabled ON acquisition_sources (enabled);
CREATE INDEX ix_acquisition_sources_page_format_key ON acquisition_sources (page_format_key);
CREATE INDEX ix_acquisition_sources_workspace_id ON acquisition_sources (workspace_id);

-- 表名：gallery_photos
-- 表说明：展示图库图片及其展示顺序
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   filename：原始文件名
--   content_type：文件 MIME 类型
--   sha256：文件内容 SHA-256 摘要
--   object_key：对象存储中的文件键
--   width：媒体宽度，单位为像素
--   height：媒体高度，单位为像素
--   taken_at：媒体拍摄时间
--   is_rich_text：是否为携带图文内容的图库图片
--   ingest_source：图库入库来源：legacy_unclassified（历史未分类）、manual（手工上传）或 acquisition（采集导入）
--   rich_text：图库图文内容
--   ocr_status：图文识别状态：manual（手工录入）、ok、failed 或 empty
--   display_batch_at：图库展示批次时间，用于稳定排序
--   display_index：同一展示批次内的排序序号
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE gallery_photos (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	filename VARCHAR(512) NOT NULL, 
	content_type VARCHAR(128), 
	sha256 VARCHAR(64) NOT NULL, 
	object_key VARCHAR(512) NOT NULL, 
	width INTEGER, 
	height INTEGER, 
	taken_at DATETIME, 
	is_rich_text BOOLEAN NOT NULL, 
	ingest_source VARCHAR(32) NOT NULL, 
	rich_text TEXT, 
	ocr_status VARCHAR(32), 
	display_batch_at DATETIME NOT NULL, 
	display_index INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gallery_photos_workspace_sha256_rich_text UNIQUE (workspace_id, sha256, is_rich_text), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);
CREATE INDEX ix_gallery_photos_display_order ON gallery_photos (workspace_id, display_batch_at, display_index);
CREATE INDEX ix_gallery_photos_ingest_source ON gallery_photos (ingest_source);
CREATE INDEX ix_gallery_photos_is_rich_text ON gallery_photos (is_rich_text);
CREATE INDEX ix_gallery_photos_ocr_status ON gallery_photos (ocr_status);
CREATE INDEX ix_gallery_photos_sha256 ON gallery_photos (sha256);
CREATE INDEX ix_gallery_photos_workspace_id ON gallery_photos (workspace_id);

-- 表名：persons
-- 表说明：图片人脸识别使用的人物档案
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   name：名称
--   display_name：界面展示名称
--   note：备注
--   is_unknown：是否为系统生成的未知人物
--   unknown_serial：未知人物递增编号
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE persons (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	name VARCHAR(256) NOT NULL, 
	display_name VARCHAR(256) NOT NULL, 
	note TEXT, 
	is_unknown BOOLEAN NOT NULL, 
	unknown_serial INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_persons_workspace_name UNIQUE (workspace_id, name), 
	CONSTRAINT uq_persons_workspace_unknown_serial UNIQUE (workspace_id, unknown_serial), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_persons_display_name ON persons (display_name);
CREATE INDEX ix_persons_is_unknown ON persons (is_unknown);
CREATE INDEX ix_persons_name ON persons (name);
CREATE INDEX ix_persons_workspace_id ON persons (workspace_id);

-- 表名：tags
-- 表说明：图库和人物共用的标签定义
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   name：名称
--   is_system：是否为系统内置标签
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE tags (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	name VARCHAR(128) NOT NULL, 
	is_system BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tags_workspace_name UNIQUE (workspace_id, name), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_tags_is_system ON tags (is_system);
CREATE INDEX ix_tags_name ON tags (name);
CREATE INDEX ix_tags_workspace_id ON tags (workspace_id);

-- 表名：tasks
-- 表说明：后台异步任务进度记录
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   kind：任务类型，由发起任务的业务模块定义
--   status：任务状态：pending、running、completed、failed 或 canceled
--   message：任务进度或结果说明
--   progress：任务完成进度，范围为 0 到 1
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE tasks (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	kind VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	message TEXT, 
	progress FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_tasks_workspace_id ON tasks (workspace_id);

-- 表名：upload_history
-- 表说明：历史上传批次汇总记录
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   upload_type：上传类型，当前为 gallery 或 rich
--   total_count：本次处理项目总数
--   success_count：本次处理成功数量
--   duplicate_count：重复数量
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE upload_history (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	upload_type VARCHAR(32) NOT NULL, 
	total_count INTEGER NOT NULL, 
	success_count INTEGER NOT NULL, 
	duplicate_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_upload_history_created_at ON upload_history (created_at);
CREATE INDEX ix_upload_history_upload_type ON upload_history (upload_type);
CREATE INDEX ix_upload_history_workspace_id ON upload_history (workspace_id);

-- 表名：video_category_tags
-- 表说明：视频分类标签定义
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   name：名称
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE video_category_tags (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	name VARCHAR(128) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_category_tags_workspace_name UNIQUE (workspace_id, name), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_video_category_tags_name ON video_category_tags (name);
CREATE INDEX ix_video_category_tags_workspace_id ON video_category_tags (workspace_id);

-- 表名：video_items
-- 表说明：视频库中的视频文件及处理状态
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   title：标题
--   description：文字说明
--   filename：原始文件名
--   content_type：文件 MIME 类型
--   sha256：文件内容 SHA-256 摘要
--   object_key：对象存储中的文件键
--   cover_object_key：对象存储中的视频封面文件键
--   cover_content_type：视频封面文件 MIME 类型
--   size_bytes：文件大小，单位为字节
--   duration_seconds：视频时长，单位为秒
--   width：媒体宽度，单位为像素
--   height：媒体高度，单位为像素
--   original_video_codec：原始视频编码格式
--   original_audio_codec：原始音频编码格式
--   video_codec：处理后视频编码格式
--   audio_codec：处理后音频编码格式
--   status：视频处理状态：uploaded、processing、ready 或 processing_failed
--   faststart_applied：是否已优化视频流式播放元数据
--   seek_optimized：是否已完成视频拖动定位优化
--   seek_optimized_at：视频拖动定位优化完成时间
--   seek_keyframe_interval_seconds：优化后关键帧间隔，单位为秒
--   processed_at：媒体处理完成时间
--   processing_error：视频处理失败原因
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE video_items (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	title VARCHAR(256) NOT NULL, 
	description TEXT, 
	filename VARCHAR(512) NOT NULL, 
	content_type VARCHAR(128), 
	sha256 VARCHAR(64), 
	object_key VARCHAR(512) NOT NULL, 
	cover_object_key VARCHAR(512), 
	cover_content_type VARCHAR(128), 
	size_bytes BIGINT NOT NULL, 
	duration_seconds FLOAT, 
	width INTEGER, 
	height INTEGER, 
	original_video_codec VARCHAR(64), 
	original_audio_codec VARCHAR(64), 
	video_codec VARCHAR(64), 
	audio_codec VARCHAR(64), 
	status VARCHAR(32) NOT NULL, 
	faststart_applied BOOLEAN NOT NULL, 
	seek_optimized BOOLEAN NOT NULL, 
	seek_optimized_at DATETIME, 
	seek_keyframe_interval_seconds FLOAT, 
	processed_at DATETIME, 
	processing_error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_items_workspace_filename_size UNIQUE (workspace_id, filename, size_bytes), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	UNIQUE (object_key), 
	UNIQUE (cover_object_key)
);
CREATE INDEX ix_video_items_created_at ON video_items (created_at);
CREATE INDEX ix_video_items_sha256 ON video_items (sha256);
CREATE INDEX ix_video_items_status ON video_items (status);
CREATE INDEX ix_video_items_title ON video_items (title);
CREATE INDEX ix_video_items_workspace_id ON video_items (workspace_id);

-- 表名：video_people
-- 表说明：视频人物档案
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   name：名称
--   note：备注
--   avatar_object_key：对象存储中的人物头像文件键
--   avatar_content_type：人物头像文件 MIME 类型
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE video_people (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	name VARCHAR(256) NOT NULL, 
	note TEXT, 
	avatar_object_key VARCHAR(512), 
	avatar_content_type VARCHAR(128), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_people_workspace_name UNIQUE (workspace_id, name), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	UNIQUE (avatar_object_key)
);
CREATE INDEX ix_video_people_name ON video_people (name);
CREATE INDEX ix_video_people_workspace_id ON video_people (workspace_id);

-- 表名：video_upload_sessions
-- 表说明：视频分片上传会话
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   filename：原始文件名
--   title：标题
--   description：文字说明
--   content_type：文件 MIME 类型
--   size_bytes：文件大小，单位为字节
--   part_size：上传分片大小，单位为字节
--   total_parts：上传分片总数
--   sha256：文件内容 SHA-256 摘要
--   status：分片上传会话状态：uploading、completed、failed 或 canceled
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE video_upload_sessions (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	filename VARCHAR(512) NOT NULL, 
	title VARCHAR(256) NOT NULL, 
	description TEXT, 
	content_type VARCHAR(128), 
	size_bytes BIGINT NOT NULL, 
	part_size BIGINT NOT NULL, 
	total_parts INTEGER NOT NULL, 
	sha256 VARCHAR(64), 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_video_upload_sessions_status ON video_upload_sessions (status);
CREATE INDEX ix_video_upload_sessions_workspace_id ON video_upload_sessions (workspace_id);

-- 表名：workspace_invitations
-- 表说明：工作区成员邀请及待生效权限
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   inviter_user_id：发起邀请的用户标识
--   invitee_user_id：被邀请的用户标识
--   role：受邀后的成员角色：admin 或 member
--   status：邀请状态：pending、accepted、declined 或 revoked
--   can_add_gallery：是否允许新增图库图片
--   can_delete_gallery：是否允许删除图库图片
--   can_edit_gallery：是否允许编辑图库图片
--   can_add_samples：是否允许新增人物样本
--   can_delete_samples：是否允许删除人物样本
--   can_edit_samples：是否允许编辑人物样本
--   can_add_videos：是否允许新增视频
--   can_delete_videos：是否允许删除视频
--   can_edit_videos：是否允许编辑视频
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE workspace_invitations (
	id INTEGER NOT NULL, 
	workspace_id INTEGER NOT NULL, 
	inviter_user_id INTEGER NOT NULL, 
	invitee_user_id INTEGER NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	can_add_gallery BOOLEAN NOT NULL, 
	can_delete_gallery BOOLEAN NOT NULL, 
	can_edit_gallery BOOLEAN NOT NULL, 
	can_add_samples BOOLEAN NOT NULL, 
	can_delete_samples BOOLEAN NOT NULL, 
	can_edit_samples BOOLEAN NOT NULL, 
	can_add_videos BOOLEAN NOT NULL, 
	can_delete_videos BOOLEAN NOT NULL, 
	can_edit_videos BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(inviter_user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(invitee_user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_workspace_invitations_invitee_user_id ON workspace_invitations (invitee_user_id);
CREATE INDEX ix_workspace_invitations_inviter_user_id ON workspace_invitations (inviter_user_id);
CREATE INDEX ix_workspace_invitations_status ON workspace_invitations (status);
CREATE INDEX ix_workspace_invitations_workspace_id ON workspace_invitations (workspace_id);

-- 表名：workspace_members
-- 表说明：工作区成员及其资源权限
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   user_id：关联用户标识
--   role：成员角色：owner、admin 或 member
--   can_add_gallery：是否允许新增图库图片
--   can_delete_gallery：是否允许删除图库图片
--   can_edit_gallery：是否允许编辑图库图片
--   can_add_samples：是否允许新增人物样本
--   can_delete_samples：是否允许删除人物样本
--   can_edit_samples：是否允许编辑人物样本
--   can_add_videos：是否允许新增视频
--   can_delete_videos：是否允许删除视频
--   can_edit_videos：是否允许编辑视频
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE workspace_members (
	id INTEGER NOT NULL, 
	workspace_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	can_add_gallery BOOLEAN NOT NULL, 
	can_delete_gallery BOOLEAN NOT NULL, 
	can_edit_gallery BOOLEAN NOT NULL, 
	can_add_samples BOOLEAN NOT NULL, 
	can_delete_samples BOOLEAN NOT NULL, 
	can_edit_samples BOOLEAN NOT NULL, 
	can_add_videos BOOLEAN NOT NULL, 
	can_delete_videos BOOLEAN NOT NULL, 
	can_edit_videos BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_workspace_member UNIQUE (workspace_id, user_id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_workspace_members_user_id ON workspace_members (user_id);
CREATE INDEX ix_workspace_members_workspace_id ON workspace_members (workspace_id);

-- 表名：acquisition_categories
-- 表说明：采集来源下可抓取的分类目录
-- 字段说明：
--   id：主键标识
--   source_id：关联采集来源标识
--   parent_id：父级采集分类标识
--   name：名称
--   path：采集分类相对路径
--   crawl_url：采集分类抓取地址
--   notes：备注说明
--   enabled：是否启用
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_categories (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	parent_id INTEGER, 
	name VARCHAR(256) NOT NULL, 
	path VARCHAR(1024) NOT NULL, 
	crawl_url VARCHAR(2048) NOT NULL, 
	notes TEXT, 
	enabled BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_category_source_path UNIQUE (source_id, path), 
	FOREIGN KEY(source_id) REFERENCES acquisition_sources (id) ON DELETE CASCADE, 
	FOREIGN KEY(parent_id) REFERENCES acquisition_categories (id) ON DELETE SET NULL
);
CREATE INDEX ix_acquisition_categories_enabled ON acquisition_categories (enabled);
CREATE INDEX ix_acquisition_categories_parent_id ON acquisition_categories (parent_id);
CREATE INDEX ix_acquisition_categories_source_id ON acquisition_categories (source_id);

-- 表名：acquisition_import_batch_items
-- 表说明：采集入库批次内的逐图处理结果
-- 字段说明：
--   id：主键标识
--   batch_id：关联采集入库批次标识
--   asset_id：关联采集图片资产标识
--   ordinal：同一父级范围内的排序序号
--   status：导入批次项目状态：queued、processing、imported、failed 或 skipped
--   promotion_intent：入库时的人物样本提升意图
--   gallery_photo_id：关联图库图片标识
--   attempt_count：处理尝试次数
--   error_message：失败或异常原因
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_import_batch_items (
	id INTEGER NOT NULL, 
	batch_id VARCHAR(64) NOT NULL, 
	asset_id VARCHAR(64) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	promotion_intent VARCHAR(32), 
	gallery_photo_id INTEGER, 
	attempt_count INTEGER NOT NULL, 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_import_batch_asset UNIQUE (batch_id, asset_id), 
	CONSTRAINT uq_acquisition_import_batch_ordinal UNIQUE (batch_id, ordinal), 
	FOREIGN KEY(batch_id) REFERENCES acquisition_import_batches (id) ON DELETE CASCADE, 
	FOREIGN KEY(asset_id) REFERENCES acquisition_assets (id) ON DELETE RESTRICT, 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE SET NULL
);
CREATE INDEX ix_acquisition_import_batch_items_asset_id ON acquisition_import_batch_items (asset_id);
CREATE INDEX ix_acquisition_import_batch_items_batch_id ON acquisition_import_batch_items (batch_id);
CREATE INDEX ix_acquisition_import_batch_items_gallery_photo_id ON acquisition_import_batch_items (gallery_photo_id);
CREATE INDEX ix_acquisition_import_batch_items_status ON acquisition_import_batch_items (status);

-- 表名：acquisition_similarity_candidates
-- 表说明：采集资产与资产或图库图片的相似候选
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   scan_task_id：关联相似度扫描任务标识
--   asset_id：关联采集图片资产标识
--   other_asset_id：关联的另一采集图片资产标识
--   gallery_photo_id：关联图库图片标识
--   score：相似度得分
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE acquisition_similarity_candidates (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	scan_task_id VARCHAR(64), 
	asset_id VARCHAR(64) NOT NULL, 
	other_asset_id VARCHAR(64), 
	gallery_photo_id INTEGER, 
	score FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_similarity_candidate UNIQUE (asset_id, other_asset_id, gallery_photo_id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(scan_task_id) REFERENCES tasks (id) ON DELETE SET NULL, 
	FOREIGN KEY(asset_id) REFERENCES acquisition_assets (id) ON DELETE CASCADE, 
	FOREIGN KEY(other_asset_id) REFERENCES acquisition_assets (id) ON DELETE CASCADE, 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE CASCADE
);
CREATE INDEX ix_acquisition_similarity_candidates_asset_id ON acquisition_similarity_candidates (asset_id);
CREATE INDEX ix_acquisition_similarity_candidates_gallery_photo_id ON acquisition_similarity_candidates (gallery_photo_id);
CREATE INDEX ix_acquisition_similarity_candidates_other_asset_id ON acquisition_similarity_candidates (other_asset_id);
CREATE INDEX ix_acquisition_similarity_candidates_scan_task_id ON acquisition_similarity_candidates (scan_task_id);
CREATE INDEX ix_acquisition_similarity_candidates_workspace_id ON acquisition_similarity_candidates (workspace_id);

-- 表名：acquisition_source_scripts
-- 表说明：采集来源启用的脚本及默认参数
-- 字段说明：
--   id：主键标识
--   source_id：关联采集来源标识
--   script_key：关联采集脚本唯一键
--   enabled：是否启用
--   default_parameters_json：采集脚本默认参数，JSON 对象
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_source_scripts (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	script_key VARCHAR(128) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	default_parameters_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_source_script UNIQUE (source_id, script_key), 
	FOREIGN KEY(source_id) REFERENCES acquisition_sources (id) ON DELETE CASCADE, 
	FOREIGN KEY(script_key) REFERENCES acquisition_scripts ("key") ON DELETE CASCADE
);
CREATE INDEX ix_acquisition_source_scripts_enabled ON acquisition_source_scripts (enabled);
CREATE INDEX ix_acquisition_source_scripts_script_key ON acquisition_source_scripts (script_key);
CREATE INDEX ix_acquisition_source_scripts_source_id ON acquisition_source_scripts (source_id);

-- 表名：face_recognition_corrections
-- 表说明：人工纠正人脸识别结果的训练反馈记录
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   gallery_photo_id：关联图库图片标识
--   face_record_id：关联人脸记录标识
--   predicted_person_id：识别模型第一候选人物标识
--   predicted_score：识别模型第一候选得分
--   second_person_id：识别模型第二候选人物标识
--   second_score：识别模型第二候选得分
--   corrected_person_id：人工纠正后确认的人物标识
--   embedding_version：人脸或图片特征向量版本
--   promoted_to_sample：纠正结果是否已提升为人物样本
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE face_recognition_corrections (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	gallery_photo_id INTEGER, 
	face_record_id INTEGER, 
	predicted_person_id INTEGER, 
	predicted_score FLOAT, 
	second_person_id INTEGER, 
	second_score FLOAT, 
	corrected_person_id INTEGER NOT NULL, 
	embedding_version VARCHAR(64) NOT NULL, 
	promoted_to_sample BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE SET NULL, 
	FOREIGN KEY(corrected_person_id) REFERENCES persons (id) ON DELETE CASCADE
);
CREATE INDEX ix_face_recognition_corrections_corrected_person_id ON face_recognition_corrections (corrected_person_id);
CREATE INDEX ix_face_recognition_corrections_created_at ON face_recognition_corrections (created_at);
CREATE INDEX ix_face_recognition_corrections_gallery_photo_id ON face_recognition_corrections (gallery_photo_id);
CREATE INDEX ix_face_recognition_corrections_workspace_id ON face_recognition_corrections (workspace_id);

-- 表名：gallery_photo_person_tags
-- 表说明：图库图片与人物的关联关系
-- 字段说明：
--   id：主键标识
--   gallery_photo_id：关联图库图片标识
--   person_id：关联人物标识
--   source：人物标注来源：auto（自动识别）或 manual（人工标注）
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE gallery_photo_person_tags (
	id INTEGER NOT NULL, 
	gallery_photo_id INTEGER NOT NULL, 
	person_id INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gallery_photo_person UNIQUE (gallery_photo_id, person_id), 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE CASCADE, 
	FOREIGN KEY(person_id) REFERENCES persons (id) ON DELETE CASCADE
);
CREATE INDEX ix_gallery_photo_person_tags_gallery_photo_id ON gallery_photo_person_tags (gallery_photo_id);
CREATE INDEX ix_gallery_photo_person_tags_person_id ON gallery_photo_person_tags (person_id);

-- 表名：gallery_photo_tags
-- 表说明：图库图片与标签的关联关系
-- 字段说明：
--   id：主键标识
--   gallery_photo_id：关联图库图片标识
--   tag_id：关联标签标识
--   source：图片标签来源：manual（人工标注）或 auto（自动生成）
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE gallery_photo_tags (
	id INTEGER NOT NULL, 
	gallery_photo_id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gallery_photo_tag UNIQUE (gallery_photo_id, tag_id), 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);
CREATE INDEX ix_gallery_photo_tags_gallery_photo_id ON gallery_photo_tags (gallery_photo_id);
CREATE INDEX ix_gallery_photo_tags_tag_id ON gallery_photo_tags (tag_id);

-- 表名：gallery_similarity_features
-- 表说明：图库图片相似度检索特征与向量同步状态
-- 字段说明：
--   gallery_photo_id：关联图库图片标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   sha256：文件内容 SHA-256 摘要
--   feature_version：相似度特征提取算法版本
--   phash：感知哈希值
--   dhash：差异哈希值
--   blur_score：人脸清晰度评分
--   quality_score：图片质量评分
--   vector_point_id：向量库中的点标识
--   vector_ready：图片向量是否已写入向量库
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE gallery_similarity_features (
	gallery_photo_id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	sha256 VARCHAR(64) NOT NULL, 
	feature_version VARCHAR(64) NOT NULL, 
	phash VARCHAR(64) NOT NULL, 
	dhash VARCHAR(64) NOT NULL, 
	blur_score FLOAT NOT NULL, 
	quality_score FLOAT NOT NULL, 
	vector_point_id VARCHAR(64), 
	vector_ready BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (gallery_photo_id), 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE CASCADE, 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
);
CREATE INDEX ix_gallery_similarity_features_feature_version ON gallery_similarity_features (feature_version);
CREATE INDEX ix_gallery_similarity_features_sha256 ON gallery_similarity_features (sha256);
CREATE INDEX ix_gallery_similarity_features_vector_point_id ON gallery_similarity_features (vector_point_id);
CREATE INDEX ix_gallery_similarity_features_vector_ready ON gallery_similarity_features (vector_ready);
CREATE INDEX ix_gallery_similarity_features_workspace_id ON gallery_similarity_features (workspace_id);

-- 表名：gallery_similarity_scans
-- 表说明：图库相似图片扫描任务
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   task_id：关联后台任务标识
--   person_id：关联人物标识
--   include_cross_type：是否跨普通图与图文图进行比较
--   status：相似度扫描状态：pending、running、completed 或 failed
--   is_stale：扫描结果是否因图库变化而过期
--   feature_version：相似度特征提取算法版本
--   photo_count：纳入扫描的图片数量
--   candidate_pair_count：相似候选图片对数量
--   group_count：扫描生成的相似图片分组数量
--   error_message：失败或异常原因
--   created_at：记录创建时间（上海时区无时区值）
--   completed_at：处理完成时间
CREATE TABLE gallery_similarity_scans (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	task_id VARCHAR(64), 
	person_id INTEGER, 
	include_cross_type BOOLEAN NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	is_stale BOOLEAN NOT NULL, 
	feature_version VARCHAR(64) NOT NULL, 
	photo_count INTEGER NOT NULL, 
	candidate_pair_count INTEGER NOT NULL, 
	group_count INTEGER NOT NULL, 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE SET NULL, 
	FOREIGN KEY(person_id) REFERENCES persons (id) ON DELETE SET NULL
);
CREATE INDEX ix_gallery_similarity_scans_created_at ON gallery_similarity_scans (created_at);
CREATE INDEX ix_gallery_similarity_scans_is_stale ON gallery_similarity_scans (is_stale);
CREATE INDEX ix_gallery_similarity_scans_person_id ON gallery_similarity_scans (person_id);
CREATE INDEX ix_gallery_similarity_scans_status ON gallery_similarity_scans (status);
CREATE INDEX ix_gallery_similarity_scans_task_id ON gallery_similarity_scans (task_id);
CREATE INDEX ix_gallery_similarity_scans_workspace_id ON gallery_similarity_scans (workspace_id);

-- 表名：person_tags
-- 表说明：人物与标签的关联关系
-- 字段说明：
--   id：主键标识
--   person_id：关联人物标识
--   tag_id：关联标签标识
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE person_tags (
	id INTEGER NOT NULL, 
	person_id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_person_tag UNIQUE (person_id, tag_id), 
	FOREIGN KEY(person_id) REFERENCES persons (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);
CREATE INDEX ix_person_tags_person_id ON person_tags (person_id);
CREATE INDEX ix_person_tags_tag_id ON person_tags (tag_id);

-- 表名：sample_photos
-- 表说明：人物识别样本图片
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   person_id：关联人物标识
--   filename：原始文件名
--   content_type：文件 MIME 类型
--   sha256：文件内容 SHA-256 摘要
--   object_key：对象存储中的文件键
--   width：媒体宽度，单位为像素
--   height：媒体高度，单位为像素
--   taken_at：媒体拍摄时间
--   status：样本人脸处理状态：pending、processing、ready、error、no_face、multi_face 或 low_quality
--   error_message：失败或异常原因
--   quality_status：样本质量状态：good、warning 或 rejected
--   quality_warnings：图片质量告警，JSON 或文本
--   source_type：样本来源类型：upload（上传）或 gallery（由图库提升）
--   source_gallery_photo_id：关联的原始图库图片标识
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE sample_photos (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	person_id INTEGER NOT NULL, 
	filename VARCHAR(512) NOT NULL, 
	content_type VARCHAR(128), 
	sha256 VARCHAR(64) NOT NULL, 
	object_key VARCHAR(512) NOT NULL, 
	width INTEGER, 
	height INTEGER, 
	taken_at DATETIME, 
	status VARCHAR(32) NOT NULL, 
	error_message TEXT, 
	quality_status VARCHAR(32), 
	quality_warnings TEXT, 
	source_type VARCHAR(32) NOT NULL, 
	source_gallery_photo_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sample_photos_workspace_sha256 UNIQUE (workspace_id, sha256), 
	CONSTRAINT uq_sample_person_source_gallery UNIQUE (person_id, source_gallery_photo_id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(person_id) REFERENCES persons (id) ON DELETE CASCADE, 
	UNIQUE (object_key), 
	FOREIGN KEY(source_gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE SET NULL
);
CREATE INDEX ix_sample_photos_person_id ON sample_photos (person_id);
CREATE INDEX ix_sample_photos_quality_status ON sample_photos (quality_status);
CREATE INDEX ix_sample_photos_sha256 ON sample_photos (sha256);
CREATE INDEX ix_sample_photos_source_gallery_photo_id ON sample_photos (source_gallery_photo_id);
CREATE INDEX ix_sample_photos_source_type ON sample_photos (source_type);
CREATE INDEX ix_sample_photos_status ON sample_photos (status);
CREATE INDEX ix_sample_photos_workspace_id ON sample_photos (workspace_id);

-- 表名：video_item_category_tags
-- 表说明：视频与分类标签的关联关系
-- 字段说明：
--   id：主键标识
--   video_id：关联视频标识
--   tag_id：关联标签标识
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE video_item_category_tags (
	id INTEGER NOT NULL, 
	video_id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_item_category_tag UNIQUE (video_id, tag_id), 
	FOREIGN KEY(video_id) REFERENCES video_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES video_category_tags (id) ON DELETE CASCADE
);
CREATE INDEX ix_video_item_category_tags_tag_id ON video_item_category_tags (tag_id);
CREATE INDEX ix_video_item_category_tags_video_id ON video_item_category_tags (video_id);

-- 表名：video_item_people
-- 表说明：视频与人物的关联关系
-- 字段说明：
--   id：主键标识
--   video_id：关联视频标识
--   person_id：关联人物标识
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE video_item_people (
	id INTEGER NOT NULL, 
	video_id INTEGER NOT NULL, 
	person_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_item_person UNIQUE (video_id, person_id), 
	FOREIGN KEY(video_id) REFERENCES video_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(person_id) REFERENCES video_people (id) ON DELETE CASCADE
);
CREATE INDEX ix_video_item_people_person_id ON video_item_people (person_id);
CREATE INDEX ix_video_item_people_video_id ON video_item_people (video_id);

-- 表名：video_subtitle_tracks
-- 表说明：视频字幕轨道及生成状态
-- 字段说明：
--   id：主键标识
--   video_id：关联视频标识
--   language：字幕语言代码，如 zh-CN
--   label：字幕轨道显示名称
--   source_language：字幕原始语言代码
--   provider：字幕生成服务提供方标识
--   status：字幕轨状态：pending、running、ready、failed 或 canceled
--   content_vtt：WebVTT 字幕文本内容
--   error_message：失败或异常原因
--   task_id：关联后台任务标识
--   generated_at：字幕生成完成时间
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE video_subtitle_tracks (
	id INTEGER NOT NULL, 
	video_id INTEGER NOT NULL, 
	language VARCHAR(16) NOT NULL, 
	label VARCHAR(128) NOT NULL, 
	source_language VARCHAR(32), 
	provider VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	content_vtt TEXT, 
	error_message TEXT, 
	task_id VARCHAR(64), 
	generated_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_subtitle_track_language UNIQUE (video_id, language), 
	FOREIGN KEY(video_id) REFERENCES video_items (id) ON DELETE CASCADE
);
CREATE INDEX ix_video_subtitle_tracks_language ON video_subtitle_tracks (language);
CREATE INDEX ix_video_subtitle_tracks_status ON video_subtitle_tracks (status);
CREATE INDEX ix_video_subtitle_tracks_task_id ON video_subtitle_tracks (task_id);
CREATE INDEX ix_video_subtitle_tracks_video_id ON video_subtitle_tracks (video_id);

-- 表名：video_upload_parts
-- 表说明：视频上传会话的已上传分片
-- 字段说明：
--   id：主键标识
--   session_id：关联上传会话标识
--   part_index：上传分片序号，从 0 开始
--   object_key：对象存储中的文件键
--   size_bytes：文件大小，单位为字节
--   sha256：文件内容 SHA-256 摘要
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE video_upload_parts (
	id INTEGER NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	part_index INTEGER NOT NULL, 
	object_key VARCHAR(512) NOT NULL, 
	size_bytes BIGINT NOT NULL, 
	sha256 VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_video_upload_part UNIQUE (session_id, part_index), 
	FOREIGN KEY(session_id) REFERENCES video_upload_sessions (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);
CREATE INDEX ix_video_upload_parts_session_id ON video_upload_parts (session_id);

-- 表名：acquisition_runs
-- 表说明：一次图片采集运行的参数、进度和统计
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   source_id：关联采集来源标识
--   category_id：关联采集分类标识
--   script_key：关联采集脚本唯一键
--   script_name_snapshot：运行时采集脚本名称快照
--   script_version_snapshot：运行时采集脚本版本快照
--   source_name_snapshot：运行时采集来源名称快照
--   category_name_snapshot：运行时采集分类名称快照
--   category_url_snapshot：运行时采集分类地址快照
--   parameters_json：本次采集运行参数，JSON 对象
--   mode：采集模式：incremental（增量）或 full（全量）
--   status：采集任务状态：pending、running、completed、failed 或 interrupted
--   total_count：本次处理项目总数
--   downloaded_count：已下载数量
--   skipped_count：跳过数量
--   download_success_count：成功下载数量
--   candidate_count：候选图片数量
--   content_duplicate_count：内容重复数量
--   gallery_duplicate_count：与图库重复数量
--   resolution_duplicate_count：分辨率重复数量
--   resolution_upgrade_count：分辨率升级数量
--   ignored_count：已忽略数量
--   invalid_count：无效数量
--   error_count：失败数量
--   imported_count：成功入库数量
--   error_message：失败或异常原因
--   scan_start_page：采集扫描起始页码
--   scan_end_page：采集扫描结束页码
--   reached_collection_end：是否已到达采集列表末尾
--   stop_reason：采集提前停止原因
--   started_at：处理开始时间
--   completed_at：处理完成时间
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_runs (
	id VARCHAR(64) NOT NULL, 
	workspace_id INTEGER, 
	source_id INTEGER NOT NULL, 
	category_id INTEGER NOT NULL, 
	script_key VARCHAR(128), 
	script_name_snapshot VARCHAR(128) NOT NULL, 
	script_version_snapshot VARCHAR(64) NOT NULL, 
	source_name_snapshot VARCHAR(128) NOT NULL, 
	category_name_snapshot VARCHAR(256) NOT NULL, 
	category_url_snapshot VARCHAR(2048) NOT NULL, 
	parameters_json TEXT NOT NULL, 
	mode VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	total_count INTEGER NOT NULL, 
	downloaded_count INTEGER NOT NULL, 
	skipped_count INTEGER NOT NULL, 
	download_success_count INTEGER NOT NULL, 
	candidate_count INTEGER NOT NULL, 
	content_duplicate_count INTEGER NOT NULL, 
	gallery_duplicate_count INTEGER NOT NULL, 
	resolution_duplicate_count INTEGER NOT NULL, 
	resolution_upgrade_count INTEGER NOT NULL, 
	ignored_count INTEGER NOT NULL, 
	invalid_count INTEGER NOT NULL, 
	error_count INTEGER NOT NULL, 
	imported_count INTEGER NOT NULL, 
	error_message TEXT, 
	scan_start_page INTEGER, 
	scan_end_page INTEGER, 
	reached_collection_end BOOLEAN NOT NULL, 
	stop_reason VARCHAR(32), 
	started_at DATETIME, 
	completed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES acquisition_sources (id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES acquisition_categories (id) ON DELETE CASCADE, 
	FOREIGN KEY(script_key) REFERENCES acquisition_scripts ("key") ON DELETE SET NULL
);
CREATE INDEX ix_acquisition_runs_category_id ON acquisition_runs (category_id);
CREATE INDEX ix_acquisition_runs_created_at ON acquisition_runs (created_at);
CREATE INDEX ix_acquisition_runs_script_key ON acquisition_runs (script_key);
CREATE INDEX ix_acquisition_runs_source_id ON acquisition_runs (source_id);
CREATE INDEX ix_acquisition_runs_status ON acquisition_runs (status);
CREATE INDEX ix_acquisition_runs_workspace_id ON acquisition_runs (workspace_id);

-- 表名：acquisition_source_items
-- 表说明：采集来源中发现的远端条目
-- 字段说明：
--   id：主键标识
--   source_id：关联采集来源标识
--   category_id：关联采集分类标识
--   script_key：关联采集脚本唯一键
--   external_key：远端条目唯一键
--   remote_external_key：远端条目的外部唯一键
--   source_url：远端条目或图片地址
--   preview_url：远端预览图片地址
--   title：标题
--   status：采集条目状态：pending、pending_review、gallery_duplicate、imported、rejected、failed 或 ignored_video
--   last_error：最近一次处理失败原因
--   last_seen_at：最近一次发现时间
--   failed_at：处理失败时间
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_source_items (
	id INTEGER NOT NULL, 
	source_id INTEGER NOT NULL, 
	category_id INTEGER, 
	script_key VARCHAR(128), 
	external_key VARCHAR(256) NOT NULL, 
	remote_external_key VARCHAR(256), 
	source_url VARCHAR(2048) NOT NULL, 
	preview_url VARCHAR(2048), 
	title VARCHAR(512), 
	status VARCHAR(32) NOT NULL, 
	last_error TEXT, 
	last_seen_at DATETIME NOT NULL, 
	failed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_source_item_external_key UNIQUE (source_id, external_key), 
	FOREIGN KEY(source_id) REFERENCES acquisition_sources (id) ON DELETE CASCADE, 
	FOREIGN KEY(category_id) REFERENCES acquisition_categories (id) ON DELETE SET NULL, 
	FOREIGN KEY(script_key) REFERENCES acquisition_scripts ("key") ON DELETE SET NULL
);
CREATE INDEX ix_acquisition_source_items_category_id ON acquisition_source_items (category_id);
CREATE INDEX ix_acquisition_source_items_remote_external_key ON acquisition_source_items (remote_external_key);
CREATE INDEX ix_acquisition_source_items_script_key ON acquisition_source_items (script_key);
CREATE INDEX ix_acquisition_source_items_source_id ON acquisition_source_items (source_id);
CREATE INDEX ix_acquisition_source_items_status ON acquisition_source_items (status);

-- 表名：face_records
-- 表说明：样本图或图库图片中检测到的人脸及识别决策
-- 字段说明：
--   id：主键标识
--   workspace_id：所属工作区标识；为空表示历史全局数据
--   sample_photo_id：关联人物样本图片标识
--   gallery_photo_id：关联图库图片标识
--   bbox_left：人脸框左边界像素坐标
--   bbox_top：人脸框上边界像素坐标
--   bbox_right：人脸框右边界像素坐标
--   bbox_bottom：人脸框下边界像素坐标
--   detection_score：人脸检测置信度
--   matched_person_id：最终匹配人物标识
--   predicted_person_id：识别模型第一候选人物标识
--   match_score：最终匹配人物相似度得分
--   second_person_id：识别模型第二候选人物标识
--   second_match_score：第二候选人物相似度得分
--   match_margin：第一候选与第二候选得分差值
--   rejection_reason：识别结果被拒绝的原因，如低分或差距不足
--   recognition_adapter_id：执行识别的人脸模型适配器标识
--   decision_threshold：识别接受阈值快照
--   decision_min_margin：识别接受所需最小得分差快照
--   embedding_version：人脸或图片特征向量版本
--   face_size：人脸框尺寸指标
--   blur_score：人脸清晰度评分
--   pose_yaw：人脸水平偏转角度
--   needs_review：是否需要人工复核
--   vector_collection：保存人脸向量的向量库集合名
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE face_records (
	id INTEGER NOT NULL, 
	workspace_id INTEGER, 
	sample_photo_id INTEGER, 
	gallery_photo_id INTEGER, 
	bbox_left FLOAT NOT NULL, 
	bbox_top FLOAT NOT NULL, 
	bbox_right FLOAT NOT NULL, 
	bbox_bottom FLOAT NOT NULL, 
	detection_score FLOAT, 
	matched_person_id INTEGER, 
	predicted_person_id INTEGER, 
	match_score FLOAT, 
	second_person_id INTEGER, 
	second_match_score FLOAT, 
	match_margin FLOAT, 
	rejection_reason VARCHAR(32), 
	recognition_adapter_id VARCHAR(64), 
	decision_threshold FLOAT, 
	decision_min_margin FLOAT, 
	embedding_version VARCHAR(64), 
	face_size FLOAT, 
	blur_score FLOAT, 
	pose_yaw FLOAT, 
	needs_review BOOLEAN NOT NULL, 
	vector_collection VARCHAR(32), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE, 
	FOREIGN KEY(sample_photo_id) REFERENCES sample_photos (id) ON DELETE CASCADE, 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE CASCADE, 
	FOREIGN KEY(matched_person_id) REFERENCES persons (id) ON DELETE SET NULL
);
CREATE INDEX ix_face_records_gallery_photo_id ON face_records (gallery_photo_id);
CREATE INDEX ix_face_records_matched_person_id ON face_records (matched_person_id);
CREATE INDEX ix_face_records_needs_review ON face_records (needs_review);
CREATE INDEX ix_face_records_predicted_person_id ON face_records (predicted_person_id);
CREATE INDEX ix_face_records_workspace_id ON face_records (workspace_id);

-- 表名：gallery_similarity_groups
-- 表说明：单次图库相似度扫描产出的图片分组
-- 字段说明：
--   id：主键标识
--   scan_id：关联相似度扫描标识
--   ordinal：同一父级范围内的排序序号
--   tier：相似分组等级
--   review_status：相似图片分组审核状态，当前为 pending、approved 或 rejected
--   min_score：分组内最低相似度得分
--   average_score：分组内平均相似度得分
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE gallery_similarity_groups (
	id INTEGER NOT NULL, 
	scan_id VARCHAR(64) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	tier VARCHAR(32) NOT NULL, 
	review_status VARCHAR(32) NOT NULL, 
	min_score FLOAT NOT NULL, 
	average_score FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gallery_similarity_group_ordinal UNIQUE (scan_id, ordinal), 
	FOREIGN KEY(scan_id) REFERENCES gallery_similarity_scans (id) ON DELETE CASCADE
);
CREATE INDEX ix_gallery_similarity_groups_review_status ON gallery_similarity_groups (review_status);
CREATE INDEX ix_gallery_similarity_groups_scan_id ON gallery_similarity_groups (scan_id);
CREATE INDEX ix_gallery_similarity_groups_tier ON gallery_similarity_groups (tier);

-- 表名：acquisition_imported_photos
-- 表说明：采集资产入图库后的图片映射
-- 字段说明：
--   id：主键标识
--   run_id：关联采集运行标识
--   asset_id：关联采集图片资产标识
--   gallery_photo_id：关联图库图片标识
--   gallery_photo_snapshot_id：入库时记录的图库图片标识快照
--   filename_snapshot：入库时记录的文件名快照
--   sha256_snapshot：入库时记录的 SHA-256 摘要快照
--   category_path_snapshot：入库时记录的采集分类路径快照
--   created_at：记录创建时间（上海时区无时区值）
CREATE TABLE acquisition_imported_photos (
	id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	asset_id VARCHAR(64) NOT NULL, 
	gallery_photo_id INTEGER, 
	gallery_photo_snapshot_id INTEGER NOT NULL, 
	filename_snapshot VARCHAR(512) NOT NULL, 
	sha256_snapshot VARCHAR(64) NOT NULL, 
	category_path_snapshot VARCHAR(1024) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_imported_run_asset UNIQUE (run_id, asset_id), 
	FOREIGN KEY(run_id) REFERENCES acquisition_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(asset_id) REFERENCES acquisition_assets (id) ON DELETE RESTRICT, 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE SET NULL
);
CREATE INDEX ix_acquisition_imported_photos_asset_id ON acquisition_imported_photos (asset_id);
CREATE INDEX ix_acquisition_imported_photos_gallery_photo_id ON acquisition_imported_photos (gallery_photo_id);
CREATE INDEX ix_acquisition_imported_photos_run_id ON acquisition_imported_photos (run_id);

-- 表名：acquisition_run_items
-- 表说明：采集运行与候选图片资产的处理明细
-- 字段说明：
--   id：主键标识
--   run_id：关联采集运行标识
--   source_item_id：关联远端采集条目标识
--   asset_id：关联采集图片资产标识
--   status：采集运行条目状态：pending、pending_review、gallery_duplicate、imported、rejected、failed、skipped 或 ignored_video
--   collection_outcome：采集条目处理结果
--   resolved_url：解析后的实际下载地址
--   resolved_candidate：采用的候选下载地址类型
--   error_message：失败或异常原因
--   created_at：记录创建时间（上海时区无时区值）
--   updated_at：记录最后更新时间（上海时区无时区值）
CREATE TABLE acquisition_run_items (
	id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	source_item_id INTEGER NOT NULL, 
	asset_id VARCHAR(64), 
	status VARCHAR(32) NOT NULL, 
	collection_outcome VARCHAR(32) NOT NULL, 
	resolved_url VARCHAR(2048), 
	resolved_candidate VARCHAR(32), 
	error_message TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acquisition_run_source_item UNIQUE (run_id, source_item_id), 
	FOREIGN KEY(run_id) REFERENCES acquisition_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_item_id) REFERENCES acquisition_source_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(asset_id) REFERENCES acquisition_assets (id) ON DELETE SET NULL
);
CREATE INDEX ix_acquisition_run_items_asset_id ON acquisition_run_items (asset_id);
CREATE INDEX ix_acquisition_run_items_collection_outcome ON acquisition_run_items (collection_outcome);
CREATE INDEX ix_acquisition_run_items_run_id ON acquisition_run_items (run_id);
CREATE INDEX ix_acquisition_run_items_source_item_id ON acquisition_run_items (source_item_id);
CREATE INDEX ix_acquisition_run_items_status ON acquisition_run_items (status);

-- 表名：gallery_similarity_group_members
-- 表说明：图库相似图片分组成员及推荐保留结果
-- 字段说明：
--   id：主键标识
--   group_id：关联相似图片分组标识
--   gallery_photo_id：关联图库图片标识
--   score_to_representative：成员相对代表图片的相似度得分
--   quality_score：图片质量评分
--   recommended_keep：是否建议保留该图片
CREATE TABLE gallery_similarity_group_members (
	id INTEGER NOT NULL, 
	group_id INTEGER NOT NULL, 
	gallery_photo_id INTEGER NOT NULL, 
	score_to_representative FLOAT NOT NULL, 
	quality_score FLOAT NOT NULL, 
	recommended_keep BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gallery_similarity_group_member UNIQUE (group_id, gallery_photo_id), 
	FOREIGN KEY(group_id) REFERENCES gallery_similarity_groups (id) ON DELETE CASCADE, 
	FOREIGN KEY(gallery_photo_id) REFERENCES gallery_photos (id) ON DELETE CASCADE
);
CREATE INDEX ix_gallery_similarity_group_members_gallery_photo_id ON gallery_similarity_group_members (gallery_photo_id);
CREATE INDEX ix_gallery_similarity_group_members_group_id ON gallery_similarity_group_members (group_id);

-- 表名：gallery_similarity_group_people
-- 表说明：图库相似图片分组关联的人物
-- 字段说明：
--   id：主键标识
--   group_id：关联相似图片分组标识
--   person_id：关联人物标识
CREATE TABLE gallery_similarity_group_people (
	id INTEGER NOT NULL, 
	group_id INTEGER NOT NULL, 
	person_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_gallery_similarity_group_person UNIQUE (group_id, person_id), 
	FOREIGN KEY(group_id) REFERENCES gallery_similarity_groups (id) ON DELETE CASCADE, 
	FOREIGN KEY(person_id) REFERENCES persons (id) ON DELETE CASCADE
);
CREATE INDEX ix_gallery_similarity_group_people_group_id ON gallery_similarity_group_people (group_id);
CREATE INDEX ix_gallery_similarity_group_people_person_id ON gallery_similarity_group_people (person_id);
