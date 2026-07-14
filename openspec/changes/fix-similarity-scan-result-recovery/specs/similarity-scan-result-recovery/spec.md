## ADDED Requirements

### Requirement: 恢复最近成功扫描结果
系统 SHALL 在用户进入或刷新相似整理页面时恢复当前 workspace 最近一次成功扫描，并使用该扫描保存的人物范围和跨类型参数。

#### Scenario: 刷新非默认范围结果
- **WHEN** 最近成功扫描使用了指定人物或开启了跨类型匹配
- **THEN** 页面刷新后直接展示该扫描结果并同步对应扫描参数

#### Scenario: 没有成功结果
- **WHEN** 当前 workspace 尚无成功扫描
- **THEN** 页面显示尚未扫描状态且不得自动发起扫描

### Requirement: 按扫描范围访问保留结果
系统 SHALL 为每个 `(person_id, include_cross_type)` 扫描范围提供最近一次成功结果，并允许用户在这些结果之间切换。

#### Scenario: 查看不同范围结果
- **WHEN** 用户从历史结果入口选择另一扫描范围
- **THEN** 页面展示该范围保留的成功分组并同步人物和跨类型设置

#### Scenario: 查看过期结果
- **WHEN** 用户选择已被标记为过期的成功扫描
- **THEN** 系统继续返回完整分组并提示结果可能过期

### Requirement: 活动扫描不遮挡成功结果
系统 SHALL 分别提供当前活动扫描和成功结果，扫描进行期间旧成功结果 MUST 保持可读。

#### Scenario: 重扫进行中
- **WHEN** 用户对已有成功结果的范围发起重扫
- **THEN** 页面展示扫描进度并继续显示旧成功分组

#### Scenario: 刷新时存在活动扫描
- **WHEN** 页面刷新时 workspace 存在 pending 或 running 扫描
- **THEN** 页面恢复活动扫描进度，同时仍允许查看已保留成功结果

### Requirement: 扫描失败回退旧结果
系统 SHALL 在新扫描失败时显示失败原因，并保持同范围旧成功结果可读。

#### Scenario: 重扫失败
- **WHEN** 新扫描在特征生成或聚类过程中失败
- **THEN** 页面提示失败且不得清空或覆盖旧成功分组

### Requirement: 隔离扫描概览
系统 SHALL 只向 workspace 成员返回当前 workspace 的活动扫描和成功结果概览。

#### Scenario: 读取扫描概览
- **WHEN** workspace 成员读取相似扫描概览
- **THEN** 响应不得包含其他 workspace 的扫描记录
