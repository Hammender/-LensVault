## Why

现有 Telegram 采集只支持手工输入频道引用，无法方便选择已加入的私有频道，也无法采集机器人私聊或论坛频道的指定话题。频道评论区媒体同样没有独立开关，导致可见内容无法按用户实际会话结构配置。

## What Changes

- 增加已登录 Telegram 会话列表，支持选择频道、群组和机器人私聊。
- 保留公开频道链接、私有邀请链接、用户名和 peer ID 的手工输入入口。
- 识别论坛频道及其话题，支持扫描话题列表、手工输入话题 ID，并把每个话题作为独立采集分类。
- 支持机器人私聊中的图片和视频采集。
- 为启动采集增加评论区媒体开关，默认关闭；评论只采集图片和视频并进入现有审核流程。
- 媒体类型和评论策略在每次运行时选择，分类只保存会话与话题目标。
- 扩展 Telegram 消息元数据、分类配置和运行统计以区分会话、话题、原帖和评论。
- 重新设计图片采集页面中的 Telegram 创建器和运行参数面板。

## Capabilities

### New Capabilities

- `telegram-dialog-acquisition`: 已登录会话、机器人私聊和手工会话解析。
- `telegram-topic-acquisition`: 论坛主题发现、选择和按主题采集。
- `telegram-comment-media-acquisition`: 频道评论区媒体采集。

### Modified Capabilities

- `telegram-channel-acquisition`: 扩展频道分类、媒体类型和运行参数。
- `image-acquisition-workflow`: 采集资产增加评论来源及会话元数据。

## Impact

- 影响 `backend/app/services/telegram.py`、采集 API、采集模型、Alembic 迁移和 `sql/tables.sql`。
- 影响 `frontend/src/AcquisitionCenter.tsx`、Telegram API 类型和样式。
- 不新增 Bot API 登录，继续使用现有用户 MTProto session。
