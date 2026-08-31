## Why

图片采集中心目前只能从 HTTP 页面下载图片，无法归档 Telegram 频道中的图片、视频和文案。个人工作区需要按自己的 Telegram 账号访问频道，手动筛选并审核收藏内容。

## What Changes

- 新增工作区级 Telegram MTProto 账号登录、状态检查和注销能力。
- 新增 Telegram 频道采集脚本，支持公开频道和当前账号已加入的私人频道。
- 支持按时间范围、媒体类型、Telegram `#标签` 与文案关键词筛选消息。
- 将图片和视频统一保存到采集审核区，保留 Telegram 文案、标签、频道和消息来源信息。
- 支持审核区混合媒体的批量导入：图片进入图库，视频进入视频库。

## Capabilities

### New Capabilities
- `telegram-channel-acquisition`: 工作区隔离的 Telegram 频道登录、采集、审核与导入流程。

### Modified Capabilities

- `image-acquisition-workflow`: 采集审核资产从仅图片扩展为图片和视频。

## Impact

- 涉及采集模型、SQLite 增量迁移、采集服务、视频服务、FastAPI 接口和采集中心界面。
- 新增 Telethon 与 cryptography 依赖，以及 Telegram session 加密配置。
