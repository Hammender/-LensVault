# Telegram 登录修复与站点创建改版

## Context

试用 Telegram 采集时：填写 API ID、API Hash、手机号（未带 `+86`）后，页面提示「验证码已发送」，但 App 和短信都没收到；表单切到验证码态，原先三项无法查看或修改。Telegram 账号表单与新增分类挤在同一两列网格里。

用户希望：把 Telegram 当成一种站点；新增站点时直接选择脚本；选 Telegram 则在同一表单里继续填登录信息和验证码；待验证态用摘要展示凭证。

## Approach

登录仍按工作区绑定**一个** Telegram 账号（`telegram_accounts.workspace_id` 唯一，Telethon session 也是单用户）。多个 Telegram 站点共用该账号：第一个未登录时走验证码；已登录则创建站点时只展示已连接摘要，不再重复登录。

验证码发送与验证必须复用同一次 `StringSession`。手机号规范成 E.164（中国 11 位手机号自动补 `+86`）。新增站点表单增加脚本选择；选 Telegram 时向下展开登录字段，不再使用独立账号区。站点创建接口一次完成建站+绑脚本。

## Files to modify

- `backend/app/services/telegram.py` — 规范化手机号、保存并复用 pending session、翻译 RPC 错误、记录验证码投递方式
- `backend/app/services/acquisition.py` — `create_source` 支持 `script_key`；Telegram 站点默认 `https://t.me`；删除 `bind_script` 中未定义的 `workspace_id` 判断
- `backend/app/api/acquisition.py` — 创建站点透传脚本；登录错误处理；可选重发
- `backend/app/schemas/telegram.py`、`backend/app/schemas/acquisition.py`
- `frontend/src/types/telegram.ts`、`frontend/src/types/acquisition.ts`
- `frontend/src/api/acquisition.ts`
- `frontend/src/AcquisitionCenter.tsx`、`frontend/src/AcquisitionCenter.css`
- `backend/tests/test_telegram_acquisition.py`、`backend/tests/test_acquisition.py`

不改表结构。`pending_login_state_encrypted` 改为 JSON（手机号、`phone_code_hash`、session 字符串、投递类型）。

## Reuse

- `TelegramService.encrypt/decrypt`、`start_login` / `verify_login` / `logout`
- 现有 `bind_script`（创建站点成功后在同一请求内调用）
- 采集页 `perform()` 通知、`--acq-ink` / `--acq-teal` 视觉
- 分类侧已有 Telegram 频道入口（`createTelegramChannel`），保持不变
- 左侧站点卡片的解绑保留；未绑定脚本的旧站点仍可在卡片上补绑

## 账号与站点规则

- 工作区只有一个 Telegram 登录账号，session 加密存在 `telegram_accounts`。
- Telegram 站点是 `acquisition_sources` 记录，`page_format_key=telegram-channel-v1`，`base_url` 固定为 `https://t.me`（创建表单隐藏 URL）。
- 第二个及以后的 Telegram 站点直接复用已连接账号，表单显示「将使用已连接账号 @xxx / 脱敏手机号」。
- 退出登录是工作区级：所有 Telegram 站点采集都会不可用，需在任一 Telegram 站点卡片或再次创建流程中重新登录。
- 未登录时不允许创建 Telegram 站点（「新建站点」在账号 `active` 前禁用）。

## 登录修复要点

当前 `send_code_request` 用空 session，断开即丢；`sign_in` 再新建空 session。改为：

1. 规范化手机号后再发送：去空格/横线；11 位国内手机号补 `+86`；已是 `86...` 则补 `+`；已有 `+` 则保持；其余拒绝并提示示例 `+86138xxxx`。
2. 发送成功后把 `StringSession.save()`、`phone_code_hash`、规范化手机号、投递类型（App / 短信）写入 `pending_login_state_encrypted`。
3. 验证时用同一 session 字符串重建客户端再 `sign_in`。
4. 捕获 Telethon RPC / `FloodWaitError`，转成中文 400，不再只处理 `ValueError`。
5. 成功文案区分「请打开 Telegram 客户端查看来自 Telegram 的验证码」和「请查收短信」。
6. 待验证支持重发（用已存 api_hash 和手机号）和「修改」（回到凭证输入，下一次发送覆盖 pending）。

未收到验证码的主因：手机号没带国家区号，Telegram 可能发到错误目的地；session 丢弃则会导致即使收到码也验证失败。本机 TUN 代理下 Web Telegram 可用，且已经出现「验证码已发送」，说明 MTProto 已连通，本次不加 Telegram 代理配置。

## 界面

从 `.acquisition-forms` 去掉独立「Telegram 账号」块，恢复两列：新增站点 | 新增分类。

新增站点表单：

- 名称、脚本下拉（必选）、URL（非 Telegram 时必填）、备注。
- 脚本为 Telegram 时隐藏 URL，向下展开登录区（不用弹窗）。
- 未登录：API ID / Hash / 手机号 + 发送验证码。
- 待验证：摘要（API ID、Hash 已保存、脱敏手机号、投递方式）+ 验证码 + 两步密码 + 验证登录 / 重发 / 修改。
- 已登录：只读摘要，可退出账号。
- 编辑已有站点仍只改名称 / URL / 备注，不在此重绑脚本。

左侧 Telegram 站点卡片增加账号状态；未登录时可在卡片上重新登录；已登录显示退出。

## Steps

- [x] 规范化手机号，pending 状态改为含 session 的 JSON；发送/验证复用同一 session；翻译 RPC 错误并返回投递方式。
- [x] `TelegramAccountRead` 增加 `api_id`（不回 Hash）；必要时增加 `code_delivery`；补充重发接口或复用 start。
- [x] `AcquisitionSourceCreate` 增加可选 `script_key`；创建时绑定脚本；Telegram 站点写入 `https://t.me`；去掉 `bind_script` 里对未定义 `workspace_id` 的引用（绑 Telegram 脚本目前会 `NameError`）。
- [x] 新增站点表单加入脚本选择；选 Telegram 则展开登录摘要流；独立账号区删除；卡片上保留退出/重登。
- [x] 补登录与手机号单测、创建站点带脚本的测试；前端执行 `npm.cmd run build`。

## Verification

- 用 `+86138...` 和 11 位国内号两种输入发送验证码：应出现投递方式提示，Telegram 官方账号或短信能收到码；验证后状态为 `active`。
- 待验证态只显示摘要，可重发、修改；刷新后仍能看到 API ID 和脱敏手机号，看不到 Hash。
- 新建普通站点时必须选脚本，创建后左侧已绑定，不必再走「先建站再绑脚本」。
- 新建 Telegram 站点：未登录时不能提交；登录成功后站点出现且脚本已绑定；再新建第二个 Telegram 站点不要求重新登录。
- 退出账号后，添加频道应失败并提示需重新登录。
- 运行 `backend/tests/test_telegram_acquisition.py`、`backend/tests/test_acquisition.py` 中与站点创建/绑定相关的用例，以及 `cmd /c npm.cmd run build`。不启动前后端。
