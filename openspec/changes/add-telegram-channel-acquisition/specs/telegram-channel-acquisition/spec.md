## ADDED Requirements

### Requirement: 工作区 Telegram 账号
系统 SHALL 允许每个工作区绑定一个独立的 Telegram MTProto 账号，并加密保存其登录凭证和 session。

#### Scenario: 工作区所有者完成登录
- **WHEN** 工作区所有者提交有效的 API 凭证、手机号和验证码
- **THEN** 系统 SHALL 为当前工作区保存已登录账号且不在响应中返回敏感凭证

#### Scenario: 其他工作区无法读取账号
- **WHEN** 用户切换到另一个工作区
- **THEN** 系统 SHALL 不返回原工作区的 Telegram 账号或频道信息

### Requirement: Telegram 频道消息采集
系统 SHALL 允许用户手动采集当前工作区账号可访问频道中的图片和视频，并支持私人频道。

#### Scenario: 已加入的私人频道被采集
- **WHEN** 当前工作区 Telegram 账号已加入指定私人频道并启动采集
- **THEN** 系统 SHALL 读取符合筛选条件的消息媒体并进入审核区

#### Scenario: 不可访问频道
- **WHEN** 当前账号无权访问频道
- **THEN** 系统 SHALL 使运行失败并记录可读错误信息，不创建媒体资产

### Requirement: 消息筛选和来源元数据
系统 SHALL 对 Telegram 媒体按日期范围、媒体类型、标签和文案关键词执行 AND 筛选，并保存来源元数据。

#### Scenario: 全部筛选条件命中
- **WHEN** 一条媒体消息在时间范围内且匹配所有指定标签和关键词
- **THEN** 系统 SHALL 下载该媒体并保存完整 caption、标签、频道和消息标识

#### Scenario: 相册消息拆分
- **WHEN** 一条 Telegram 相册包含多个支持的媒体
- **THEN** 系统 SHALL 为每个媒体创建独立审核资产并保留同一 grouped_id

### Requirement: 混合媒体审核和批量导入
系统 SHALL 在采集审核区同时展示图片和视频，并允许批量导入。

#### Scenario: 批量导入混合选择
- **WHEN** 用户选择审核区中的图片和视频并执行导入
- **THEN** 系统 SHALL 将图片导入图库、将视频导入视频库并分别记录结果

#### Scenario: 视频默认元数据
- **WHEN** 用户导入带 caption 的视频
- **THEN** 系统 SHALL 使用 caption 首行作为标题、完整 caption 作为简介，并按时长确定短视频或长视频
