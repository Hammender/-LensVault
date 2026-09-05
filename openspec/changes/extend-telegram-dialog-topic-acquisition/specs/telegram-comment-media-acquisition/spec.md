## ADDED Requirements

### Requirement: Optional comment media
频道分类 SHALL 提供默认关闭的评论区媒体开关；开启后只采集评论中的图片和视频。

#### Scenario: Collect comments
- **WHEN** 用户开启评论媒体采集并运行频道分类
- **THEN** 读取频道帖子关联讨论线程中的图片和视频并进入待审核流程

### Requirement: Comment failure isolation
评论区读取失败 SHALL 被记录为部分失败，且不得阻断频道原帖媒体采集。

#### Scenario: Discussion unavailable
- **WHEN** 账号无法访问某个帖子的讨论组
- **THEN** 原帖继续采集，运行记录包含评论失败信息
