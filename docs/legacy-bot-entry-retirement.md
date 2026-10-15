# Bot 遗留入口归属完成（2026-10-15）

基线：Taiko `16d118d`（0.11.0），Sakura `084d13d`（9.82.14）。本批运行包为 **taiko-bot 0.12.0**，Application 0.8.0、中心 Core 0.1.1、客户端 Core 0.1.2、Contract 0.1.0 不变。

## 实际归属

`taiko_bot.runtime.community.community_entry` 在既有 NoneBot 进程注册中心、客户端各 16 个 matcher，不发行独立插件包：

- 两端 `draw_guess_switch/make_start/make_router/start/answer/like/report/view/mine/rank/manual_exit`，共 11 个。实现、会话字典、JSON 持久化、图片目录与排行榜都在 `runtime/community/{center,client}/draw_guess.py`。
- 两端 `cover_cmd`，由对应 `cover.py` 管理歌曲校验、图片下载/转换、文件检查、OSS 结果；中心继续调用已归属 Taiko 的 `player.center.admin_audit`。原客户端没有管理员审计，保持该差异。
- 中心独有 `annual_2025_report` 和 `annual_report_command.py`。仍调用 Viewer 内部 annual-card API，保持 QQ 官方限定、8 个别名、20 MiB 上限、最多 4 个并发、30 秒冷却、图片/按钮与发送回退。客户端不注册年度入口。
- 两端 `qq_official_unsupported_gate/qq_official_ping/anti_sb`；客户端另有 `anti`。中心 markdown 日志、复制 Sakura 前缀规范化、静默身份过滤原样迁到 `compat.py`；客户端保持原来的复制提示和 JSON 消息处理，不擅自增加中心静默名单。

注册声明的 matcher 类型、rule、permission、priority、block 与冻结基线 AST 一致。中心两个事件预处理器仍在 matcher 分发之前；二者不依赖彼此执行顺序。`require` 重入与正序/逆序/批量加载均无重复注册。public 仍为 9 个，player 中心 49/客户端 45 个。

中心路径默认仍为 `/home/sigaer/taiko`，测试可用 `TAIKO_CENTER_ROOT` 隔离；客户端沿用 settings.root_dir。JSON 字段、图片文件名、600 秒超时、5 次机会、5 次举报停用保持不变。不会导入 Sakura 全局字典或旧插件初始化。

## 修复与兼容边界

- 冻结中心 `draw_guess_view` 使用未定义的 `event`，原函数缺少事件参数。新处理器补齐参数，单独断言真实查看成功；基线 NameError 被明确记录为旧缺陷，未当作等价成功。
- 同群会话操作按群串行；同歌曲封面上传按 ID 串行，避免网络 await 期间重复开局、重复计奖和重复 OSS 上传。不同群/歌曲互不阻塞。锁只保留正在执行/等待的键，异常与取消后回收，不改变 JSON 格式或增加数据库表。
- 保留历史前缀规范化语义，包括前缀后的 `/` 属于可剥离分隔符；未借迁移修改命令语法。

## 统计与共享代码

Sakura `taiko/nonebot_plugin_method_calls` 整体进入 Taiko 根运行包，保留 `nonebot_plugin_method_calls` namespace。其唯一运行消费者是 Taiko 宿主 pyproject；包声明 aiomysql 和 APScheduler 依赖。

`store.py`、`cleanup.py`、`recorder.py` 与 Sakura 基线字节一致，保留 method_calls、现有 rollup、环境变量、调度与 SQL schema。运行环境加载使用既有 Taiko owner；仅供这份统计使用的 reserved_commands 同时迁走。命令注册表全部指向显式 Taiko owner，不再回落到 plugins.taiko。新增年度报告、ping、猜答案的规范化归属；会话路由、退出/兼容门禁、诊断监听不作为额外命令计数。

Sakura 根目录 `nonebot_plugin_method_calls` **不改动**；实际消费者为根 `pyproject.toml` 和 `miku_bot/pyproject.toml`，后者复用根目录包，并无另一份 miku 专用副本。通用 feature_handler、OneBot/QQ 连接与进程宿主继续由各自宿主承担；这些仍有实际消费者，不为删除太鼓入口而移除。Sakura 其他服务端/数据/工具源码不在本批范围，不能据此宣称整个仓库完全去太鼓化。

Sakura 删除：旧 `taiko/plugins/taiko.py` 2,662 行、annual_report_command 108 行、reserved_commands 25 行、统计实现 1,383 行，合计实现 **4,178 行**；连同迁走的测试共 **14 文件 / 4,668 行**。Taiko 客户端旧 `plugins/taiko.py` 2,071 行也删除，不留转发壳。

## 验证记录

全部运行于现有隔离工作树、独立中心/客户端环境，经 `scripts/memory/run_qa.sh` 限额；没有生产进程启动、部署、重启、真实玩家数据或生产 OSS 访问。

- 新入口双端：冻结处理器消息/JSON 对照；真实 OneBot/QQ 分发；成功、下载/解码/OSS 失败、重复、权限、超时、群隔离、举报停用、个人/群/全群排名；并发开局/猜中/上传和 JSON 计数；静默过滤、前缀、priority/block、一次计数。
- 合成 400×400 PNG 两端 SHA256：`fca400c943b013305527a49f93e6754582f7d0d92923c06d7f861cc8e2aaba7d`。无真实 cover 路径、OSS 或 HTTP；外部 IO 审计钩子禁止访问。
- 年度报告 8 个别名经真实 QQ 事件返回 markdown 图片与 keyboard；API 错误/超时、非 PNG/超限、并发/冷却、主动发送回退及失败清理有独立测试。
- 年度、并发、OSS 和统计单测 **37 PASS / 494 子用例 PASS**。统计断言覆盖规范化、字段、owner、实例/临时 matcher、成功一次计数、异常不计数和 rollup 合计。
- 历史中心 owner/兼容/图片/提示测试 **28 PASS**；客户端 owner/账号/迁移/token 等聚焦测试 **102 PASS**。有效测试移到当前 owner；旧阶段的冻结来源和阶段审计资料保留其历史提交语义，不作为当前运行入口。
- 代表性回归，两端各：public **18**、tinfo **15**、推荐 **16**、进度 **16**、B30 **12**、趋势 **8**、个人展示 **12**、生命周期 **46** PASS。生命周期使用既有合成 SQL/HTTP fixture，未重跑完整 Core/Application/Storage 套件。
- `tests/community/audit.py`：旧模块与统计目录不存在；正常运行代码无 plugins.taiko 依赖；年度函数体 AST 一致；统计存储实现字节一致；受保护协议/schema 零变更。两环境安装 wheel 后 pip check 通过。

可复用新测试入口：`tests/community/events.py <center|client> <冻结旧模块文件> <合成临时目录>`；先在各自环境初始化相应 profile，再运行 community 与统计 pytest。冻结文件分别取自本页基线提交，绝不能取生产运行树。年度和统计的测试均未运行 DB 启动 hooks。

证据与隔离环境位于 `/var/tmp/taiko-entry-retirement-20261015` 和 `/var/tmp/taiko-lifecycle-20261015`。本次通过源码集成交付，不授权或执行生产安装；后续服务端迁移另行安排。
