## ADDED Requirements

### Requirement: Forum topic discovery
系统 SHALL 能识别论坛会话并返回可访问的话题列表。

#### Scenario: Load topics
- **WHEN** 用户请求论坛会话的话题
- **THEN** 返回主题 ID、名称、关闭状态和置顶状态

### Requirement: Topic category
每个选定话题 SHALL 作为独立采集分类保存，并只扫描该话题消息。

#### Scenario: Collect selected topic
- **WHEN** 用户运行指定话题分类
- **THEN** 采集器不读取其他话题的消息

### Requirement: Manual topic fallback
系统 SHALL 允许用户手工输入主题 ID，并在主题列表不可用时继续创建分类。

#### Scenario: Manual topic ID
- **WHEN** 用户输入有效主题 ID
- **THEN** 分类保存该 ID 并在运行时按该 ID 过滤
