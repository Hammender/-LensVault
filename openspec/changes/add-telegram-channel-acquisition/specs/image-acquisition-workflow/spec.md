## ADDED Requirements

### Requirement: 采集审核资产媒体类型
采集审核区 SHALL 支持图片与视频资产，并维持既有图片采集和导入行为。

#### Scenario: 既有图片资产兼容
- **WHEN** 系统读取本变更前创建的采集资产
- **THEN** 系统 SHALL 将其作为图片资产展示和处理
