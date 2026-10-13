# Phase 2F-B — Public Song Commands Ownership Cutover

状态：**PHASE_2F_B_COMPLETE**。基线 Taiko `c5ef227`、Sakura `241a237`；仅迁出六个公共曲目入口，未合并 main、部署或重启。

## 实际归属变化

同一 `nonebot-plugin-taiko-song` 升为 0.2.0，新增统一注册的 `alias_query`、`song_where`、`song_position_phrase`、`song_pos_by_id`、`diff_by_id`、`note_count`。原 `what_song` 继续唯一注册。新业务/入口放在 `public_commands.py`（252 行）、`public_queries.py`（76 行）、`alias_renderer.py`（94 行）；Provider 增加 43 行公共读取/资源准入，初始化文件只增加注册 import。没有新增发行单元。

Sakura 的 `plugins/taiko.py` 移除六个 matcher、六个 handler、五个专属 helper 和正则/难度常量，共删除 259 行；聚合 utils 移除 `find_by_volume` 41 行；`duplicate_versions` 移除孤立的 `alias_entry_for_song_id` 及其 import/常量 26 行；整个已无消费者的 `song_position.py` 删除 54 行。运行源码合计删除 **380 行**。原专属测试 170 行迁由外部插件安装/分派验收覆盖，其余测试不改期望值。

客户端删除相同六类入口及五个额外孤立 helper：`_resolve_what_song_query`、`_finish_fuzzy_query_with_fumen`、`_get_fumen_path`、`_finish_with_image_fallback`、`_send_fumen_or_hint`。`plugins/taiko.py` 删除 346 行，utils 聚合删除 41 行，position 模块删除 67 行，运行源码合计 **454 行**。`file_to_bytesio` 仍服务猜歌等入口，保留。

没有第二套活动命令入口、Application 用例、Core 公式或消息发送框架。原 `center_messages` / `client_messages` / `delivery` 字节不变。通用字体、换行与 fuzzy-hint 小型 helper 在新 renderer/query 模块与仍需它们的宿主图片/查询代码之间存在明确的代码重叠；未借此扩大其他 renderer 的迁移。共享 queryMusic、重复曲目工具及其他命令相关 helper 保留原归属。

## 验收与安装

- 中心 **156**、客户端 **160** 项：真实 NoneBot matcher/rule/handler，OneBot 与 QQ 官方合成事件，逐项与各自冻结旧入口比较完整消息、发送参数及 PNG 编码 hash、pixel hash、dimensions、mode。客户端多四项资源准入失败。
- 六个原宿主 matcher 均为 0，外部各为 1；既有歌曲 matcher 仍为 1，并在两平台实际调用 Application 一次。
- 包含正常/ID/别名/模糊/重复曲目、空结果、非法输入、难度及缺谱面、物量排序/截断、开关与 mention、下架/隐藏/双打和位置排序并列。每端两个故意损坏的物量输入比较捕获的异常；未将框架吞异常视作正常业务成功。
- 中心其余 **67**、客户端其余 **63** 个 matcher 声明不变；剩余主模块函数/类分别 **301**、**237** 个 AST 不变。
- 安全热修补 helper 与 **35** 处发送前授权复核调用不变；私人 handler AST 不变，新插件不调用私人授权/成绩入口，不增加第二次复核。
- 两个全新 venv 真实安装和完整解析，pip check PASS。中心 Core **0.1.1**、客户端 Core **0.1.2**、Contract **0.1.0**、Application **0.5.0**。客户端包 **0.2.11**。安装来源与工作源码逐字节核对；不读取生产 /opt、Sakura 工作树或私人数据。
- 中心仍按隔离源码布局运行：`CENTER_SOURCE_RUNTIME_PASS` / `CENTER_WHEEL_NOT_REQUIRED`。外部插件与 Application 都是真实 wheel 安装。

完整结果、冻结源/资源 hash、精确环境锁与剩余 matcher 名单见 [acceptance](../packages/nonebot-plugin-taiko-song/tests/acceptance/summary.json)、[scope audit](../packages/nonebot-plugin-taiko-song/tests/acceptance/scope-audit.json)。复现入口见[插件说明](../packages/nonebot-plugin-taiko-song/README.md)。所有 QA 均经既有 memory run_qa 包装执行；没有重跑未改变的 2A–2E 矩阵。

## 安装顺序及剩余范围

先准备 Application 0.5.0 与插件 0.2.0 wheel，再安装客户端 0.2.11，或安装中心精确依赖后使用对应 Sakura 源码候选。新插件不能与仍注册这六个命令的旧宿主混用。跨仓审阅时先确认 Taiko 制品可用，再集成 Sakura 移除提交；本轮只交付候选，不执行合并或上线。

剩余宿主入口包括 B30、tinfo、定数、进度、推荐、段位、猜歌、机厅、年度、账号/绑定与 tset 等；清单完整列在 scope audit。共享业务已有 Application 的继续调用同一 Application，宿主命令所有权尚未迁出。本轮没有新增永久 Sakura 专属 adapter。

无未解决阻断。storage、Writer、SQL、sync、daily/history、Core 公式、Contract、Viewer 0.81.12 与生产运行树未修改；未引入 246 文件候选、Phase 6 或下一阶段。
