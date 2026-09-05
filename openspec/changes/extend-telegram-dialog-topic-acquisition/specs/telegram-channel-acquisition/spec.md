## MODIFIED Requirements

### Requirement: Telegram media filtering
Telegram 采集 SHALL 允许用户选择图片、视频或两者，并按时间、标签、文案关键词和消息范围筛选。

#### Scenario: Select image only
- **WHEN** 用户只选择图片
- **THEN** 视频消息不进入下载或审核流程

#### Scenario: Legacy category
- **WHEN** 历史分类没有新增会话字段
- **THEN** 系统使用原有 `crawl_url` 解析并采用图片视频双选和评论关闭的默认值
