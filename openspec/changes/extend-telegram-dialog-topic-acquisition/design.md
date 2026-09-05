## Context

现有实现通过 `client.get_entity(channel_ref)` 解析分类中的字符串，再使用 `iter_messages(channel)` 读取频道图片和视频。分类模型只有 `crawl_url`，消息元数据按频道帖子设计；前端也只有频道 URL 输入框。Telegram 的已加入私有频道、机器人私聊和论坛主题都需要依赖当前用户 session 才能可靠定位。

## Goals / Non-Goals

**Goals:**

- 将 Telegram 采集目标统一抽象为可访问会话。
- 支持频道、机器人私聊和论坛主题的图片/视频采集。
- 支持按频道帖子读取评论区媒体，且评论采集默认关闭。
- 保留旧分类和手工引用的兼容性。
- 在采集页面提供可搜索、可验证、可回退的配置流程。

**Non-Goals:**

- 不实现实时监听、定时任务、多账号或 Bot API token 登录。
- 不采集评论纯文本或机器人纯文本。
- 不自动生成用户无权限的私有频道邀请链接。

## Decisions

- 使用 `iter_dialogs()` 展示当前账号可访问会话；保存 peer ID 作为稳定定位键，`crawl_url` 继续作为兼容回退。
- 使用 `channels.GetFullChannelRequest` 获取频道关联讨论组；论坛主题通过 `channels.GetForumTopicsRequest` 查询，运行时使用主题 ID 过滤消息。
- 评论媒体通过频道原帖对应的讨论消息读取；单个帖子评论读取失败只计入部分失败，不中断原帖采集。
- 分类只保存目标类型、peer ID 和主题 ID；媒体类型与评论开关属于每次运行的临时参数；每个论坛主题独立为分类。
- 扩展现有 `AcquisitionTelegramMessage` 保存 `is_comment`、`root_channel_message_id`、`topic_id`、发送者和会话类型字段，保持统一资产审核流程。
- 前端在 Telegram 来源下使用两步配置器：选择会话/手工解析，再选择主题和采集选项；非 Telegram 来源保持原布局。

## Risks / Trade-offs

- [私有会话或讨论组权限不足] -> 接口返回可读错误，允许继续手工配置；运行时跳过失败评论并记录原因。
- [热门帖子评论数量过大] -> 增加评论上限和安全扫描上限，默认关闭评论采集。
- [主题名称可变] -> 主题 ID 作为唯一键，名称只用于展示和人工匹配。
- [旧分类没有 peer ID] -> 运行前沿用 `crawl_url` 解析并按默认值补齐新字段。

## Migration Plan

新增 Alembic revision，为分类、Telegram 消息增加字段并创建主题缓存表；迁移只增加结构和默认值，不改写历史资产。部署顺序为迁移、后端、前端。回滚时旧代码忽略新增字段，新数据表保留，不删除已下载对象。

## Open Questions

无。媒体类型、评论开关、主题分类关系和手工输入兼容策略已确定。
