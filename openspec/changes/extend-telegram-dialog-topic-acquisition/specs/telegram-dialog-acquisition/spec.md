## ADDED Requirements

### Requirement: Session list
系统 SHALL 为已登录 Telegram 账号提供当前可访问会话列表，并区分频道、群组和机器人私聊。

#### Scenario: List dialogs
- **WHEN** 已登录用户请求会话列表
- **THEN** 返回标题、peer ID、用户名、会话类型和机器人标记

### Requirement: Manual entity resolution
系统 SHALL 保留手工输入用户名、公开链接、私有邀请链接和 peer ID 的解析入口。

#### Scenario: Resolve manual reference
- **WHEN** 用户提交可访问的 Telegram 引用
- **THEN** 返回标准化会话信息并可用于创建分类

### Requirement: Bot private chat media
机器人私聊分类 SHALL 支持图片和视频采集，并忽略纯文本消息。

#### Scenario: Collect bot media
- **WHEN** 运行机器人私聊分类
- **THEN** 只将图片和视频送入下载与审核流程
