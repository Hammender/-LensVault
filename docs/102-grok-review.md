审查范围是 plugin 相对 origin/main 的两次提交（b3deee7 插件化、91e502a Telegram 修复），共 51 个文件。工作区里未跟踪的 .DS_Store / docs / tools 没有纳入。

方向是对的：Telegram 仍走进程内适配器，其它站点改成管理员上传 ZIP、每版本独立 venv、凭据用 AUTH_SECRET_KEY 加密且拒绝默认密钥。路径穿越、符号链接、管理员权限这些入口也有基本约束。还不能当稳定能力上线，主要风险在准备环境卡死、预览占住 worker、插件契约未真正校验、以及 Telegram「已登录会话」加载死循环。

共 7 个 bug、6 个建议、1 个 nit。

Bug

1. 插件会卡在 preparing，无法重试也卸不掉（已完成修复）
backend/app/services/acquisition_plugins/manager.py:149，配合 backend/app/api/acquisition_plugins.py:76

prepare() 先把状态写成 preparing 再 try。只有 OSError / CalledProcessError / TimeoutExpired 会变成 failed；其它异常（坏 manifest_json、非预期错误）会在 finally 里把 preparing 提交掉。_prepare_task 只吞 ValueError。uninstall() 拒绝 preparing，准备接口又只接受 uploaded/failed。进程在 venv/pip 中途退出时同样死锁。失败信息还被收成 插件依赖准备失败：{type(exc).__name__}，pip 的 stderr 进不了日志和界面。

建议：启动时把过期的 preparing 改成 failed；prepare() 捕获全部异常并写入截断后的 last_error；允许从 preparing 重试/卸载；venv/pip 的 stderr 记到服务端日志。

2. 预览在 HTTP 请求里同步下载，最长能占住 worker 一小时；停止采集也杀不掉子进程（已完成修复）
backend/app/api/acquisition_plugins.py:144，manager.py:243

preview_plugin 在请求里跑 enumerate_pages 再最多 5 次 download。download 的 subprocess.run 超时是 3600 秒，列举流还有 300 秒空闲定时。有 can_add_gallery 的用户就能把 API worker 钉住。正式任务的 stop_run 只设内存里的 abort_event，检查点在页与页之间、下载开始之前，已经跑起来的子进程不会被 terminate。

建议：预览改成短超时（30–60 秒）或短命后台任务；保存 Popen 句柄，abort 时杀掉整个进程组。

3. 插件视频会因为文件名不像视频而被拒（已完成修复）
backend/app/services/acquisition.py:650

media_type="video" 之后仍先用 content_type 和后缀白名单判断，过不了才 _probe_video_file。示例插件按 URL 路径起名，失败时落到 media.bin，于是报「返回内容不是视频」。Telegram 走另一条路径，不经过这套后缀检查。

建议：插件已声明 video 时先探测文件或嗅探字节；后缀只作为 URL 派生文件名的兜底。

4. 插件契约几乎没校验，上传/运行容易直接 500（已完成修复）
backend/app/services/acquisition_plugins/manager.py:59，contracts.py 的 ScriptParameter / RemoteItem

几处会直接炸：

• validate_manifest 用 ScriptParameter(**item)。清单里多一个 help / placeholder 会 TypeError，上传接口只捕 ValueError/JSONDecodeError，管理员看到 HTTP 500。
• 对外参数选项是 [{"value","label"}]，运行时 select 却按 option[0] 取元组。插件如果照着公开 API 写 dict options，start_run / 预览会 KeyError。
• RemoteItem(**item) 没有字段白名单，站点 JSON 多一个顶层键就 TypeError，整次采集失败。
• max_download_workers 原样透传，字符串会让 max(1, ...) TypeError。

建议：在 validate_manifest 里规范化 options、拒绝未知键、校验 RemoteItem 字段和 media_type ∈ {image,video}、要求 max_download_workers 为正整数；上传时把 TypeError 收成 400。

5. 新建 Telegram 分类时，「已登录会话」在空列表或失败后会无限重试（已完成修复）
frontend/src/pages/AcquisitionCenter.tsx:489

这次修把会话列表改成默认加载，但 effect 仍把「列表为空或仍在 loading」当成「还没加载完」。telegramDialogs.length > 0 对成功的 [] 为假，telegramDialogLoading 又在依赖里：开始请求 → loading true → effect 早退 → finally 把 loading 设回 false → effect 再跑。失败或账号没有对话时会一直打 listTelegramDialogs。这正是这条提交要修的「已登录会话」路径。

建议：按 (账号, telegram 站点) 只拉一次，用 generation token；依赖里去掉 telegramDialogLoading；重试改成用户手动触发。

6. .gitignore 只放行了这一份迁移脚本，以后的 Alembic revision 会从 git 里消失（已完成修复）
.gitignore:16

根上的 alembic/ 会匹配任意名为 alembic 的目录。新规则只 ! 了 backend/alembic/versions/20260926_19a44fe179ff_新增采集插件版本与账号配置.py，同时继续忽略 backend/alembic/versions/*。后续迁移 git status 看不见，很容易漏提交。

建议：正常跟踪 backend/alembic/（!backend/alembic/ 加 !backend/alembic/**，或不要全局忽略 alembic/），不要白名单单个 revision。

7. 插件页的顶栏「刷新」不会刷新插件状态（已完成修复）
frontend/src/pages/AcquisitionCenter.tsx:453

refreshCurrentTab 没有 plugins 分支，会落到历史导入加载，还改了历史分页状态。准备环境提示「请稍后刷新状态」之后，点页面上最显眼的刷新没用（面板内部另有按钮）。

建议：tab === "plugins" 时只刷新插件版本列表。

建议（可优化）

8. 上传先 shutil.move 再 db.commit()
manager.py:138

提交失败或唯一约束冲突时，磁盘上已有 {data_dir}/acquisition/plugins/{key}/{version}，库里没有行，再上传报「目标插件目录已存在」，卸载也清不掉。_pictureshow_worker.py 只在上传时拷贝，主机侧协议修复不会进已装版本。

建议：commit 成功后再 move，失败就删目录；prepare/activate/run 时拷当前 worker.py。

9. plugin_state 没有传给 download，每个文件都是新进程
manager.py:333

列举阶段写的 last_state 不会进 download。每个文件一次 subprocess.run，要登录的插件只能每文件重登，或把 token 塞进每条 plugin_data。last_state 和把加密密钥递给插件，还是 Telegram-as-plugin 的残留；get_definition("telegram-channel-mtproto") 实际一直走内置适配器。

建议：把 plugin_state 传进 download 并写进规范；一次运行考虑长驻 worker；删掉 Telegram 的 PluginAdapter 分支，避免以后把 session 密钥交给插件。

10. venv/pip/插件子进程继承完整服务器环境
manager.py:156

PIP_INDEX_URL、DATABASE_URL、MinIO 密钥都会进子进程。规范已经写明这不是恶意代码沙箱，但依赖的 setup.py 仍不该看到主机密钥。pip install 无 hash。PluginManager.active 只在处理上传/启用的那个进程内存里刷新，现在的单 worker uvicorn 能对上；加 --workers 后目录会过期。

建议：给子进程一套消毒过的 env；需要不信任作者时再做 hash pin；多 worker 时按请求从 DB 重载 active 目录。

11. 插件元数据按素材逐条查，published_at 格式不对会 500 审核列表
backend/app/api/acquisition.py:247

caption/hashtags/published_at 在 metadata_json 里，_asset_read 每条查一次（Telegram 已有批量查询）。非 ISO 的 published_at 会让审核列表 500。视频入库只从 AcquisitionTelegramMessage 读 caption，插件视频即使写了 metadata_json.caption 也会丢标题。

建议：批量加载 metadata_json；published_at 解析失败就丢掉；入库视频时用插件 caption。

12. 凭据列表非空就强制要「已验证账号」
backend/app/services/acquisition.py:447

文档写凭据可以是可选 Header、可以不填。插件只要声明了凭据字段（哪怕全 optional），前端和后端都要求先存并测通账号。启用新版本还会把该 script_key 下所有工作区账号打成 untested。

建议：仅当存在 required: true 字段时才要求账号；启用时只在凭据 schema 真变了才作废测试状态。

13. 采集视频入库在批处理循环里同步做 faststart
backend/app/services/acquisition.py:1567

手工上传走 BackgroundTask。这里一次耗时优化会堵住整批导入；失败后 rollback()（提交之后其实滚不到导入本身），再把已入库视频标成 processing_failed。

建议：和手工上传一样排队做 faststart，优化失败不要挡后续条目。

14. Nit：适配器包仍为测试 monkeypatch 保留 shutil/subprocess/urlopen
backend/app/services/acquisition_adapters/__init__.py:26

删掉站点适配器后，这些导入只为了 curl_request_bytes 和测试能补丁包属性。下次清理很容易误删。

建议：让 http.py 用自己的 import，测试补丁打到 app.services.acquisition_adapters.http.*。

───

完整审查稿：/var/folders/sp/1jlf4jgn471f0whl6g8blwtr0000gn/T/grok-hamender/grok-review-3d4d541d.md
摘要：/var/folders/sp/1jlf4jgn471f0whl6g8blwtr0000gn/T/grok-hamender/grok-review-summary-3d4d541d.md

优先修 1、2、4、5：准备环境死锁、预览占 worker、契约 500、Telegram 会话死循环。这四项会直接让插件管理或新建分类不可用。需要的话我可以按这个顺序改。