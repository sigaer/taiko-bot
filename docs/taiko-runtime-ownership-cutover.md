# Phase 2F-E — Taiko Runtime Ownership Cutover

日期：2026-10-14。状态：**PHASE_2F_E_RUNTIME_OWNERSHIP_COMPLETE**（独立候选，未上线）。

基线：Taiko D1 `1e7d0f9`、Sakura D1 `86a308c`、Application 0.7.0。
两仓分支均为 `feature/taiko-runtime-ownership`，工作树位于
`/var/tmp/taiko-phase2fe-20261014/{application,sakura}`。原 main 和已有 WIP 未吸收。

## 运行归属

既有 `taiko-bot` 发行包候选升为 **0.3.0**，公开命令与 tinfo 的活动实现统一在该仓维护：

| 目录 | 责任 |
| --- | --- |
| `taiko_bot.runtime.public` | 原九个公开命令的 matcher、业务接入与双宿主数据/发送差异 |
| `taiko_bot.runtime.player.entry` | 唯一 tinfo matcher/handler，Host Provider → PreparedPrivateInput → execute_score |
| `player.center` | 原中心绑定只读查询、授权、u0 准备、canonical current 捕获与来源、成绩展示输入 |
| `player.client` | 既有中心远程读取、绑定观察、数据准备与原客户端成绩卡版式 |
| `player.authority` | 两端发送前复核，含被动发送失败后再次复核 |
| `taiko_store` | 从 Sakura 原实现迁入，保留原 import namespace，供既有宿主调用 |

Sakura 删除 tinfo matcher/handler、`plugins.utils.tinfo_provider`、tinfo 专属
`prepare_score_presentation`/`generate_score_image` 和本地 `taiko_store` 源码；只在
NoneBot 加载配置中指定 Taiko 所有的入口，没有保留 tinfo 转发适配器。
新运行模块不反向 import Sakura `plugins` 或专用 utils。

本阶段维护归属覆盖已验证的九个公开命令、tinfo 及其必要存储依赖。
其他旧私人命令仍为冻结的 Sakura 遗留调用方，本轮没有迁移其 matcher，不能宣称
所有私人命令已经迁完。此后公开/tinfo 实现只改 Taiko 仓，不在 Sakura 新增太鼓专用实现。

## 单进程事件接入与发行

先以原隔离中心宿主执行实际事件分派，78 项公开回归通过；随后在相同 NoneBot
进程加载内部 public/player 入口及原宿主插件。复用原 driver 的 QQ/OneBot adapter，
没有启动第二个进程、注册第二条连接或假设 QQ/OneBot 连接可共享。
player 显式 require public，双端分别验证 public 优先、player 优先及批量装载，
共 **6/6 PASS**。这消除了先导入 player 时公开 matcher 错归属的加载顺序问题。

`nonebot-plugin-taiko-song` 的源代码移到内部 `public`，独立 `pyproject.toml` 已删除。
旧目录只保留历史测试/provenance 与退役说明，不再发行或扩展独立产品，不新增
`nonebot-plugin-taiko-*` 包。候选环境卸载旧插件后加载两个内部入口；不支持新旧同时装载。
两端完整宿主加载验收确认九个公开 matcher、一个 tinfo matcher，无旧 tinfo 注册。

同一 taiko-bot 包使用互斥宿主安装 profile：`taiko-bot[center]` 精确依赖 Core **0.1.1**，
`taiko-bot[client]` 精确依赖 Core **0.1.2**；入口检查实际安装版本。
Contract **0.1.0** 不变。Application 候选 **0.7.1** 仅兼容增加远程来源表示与
`PreparedScoreCommand.rendered_png` 数据输入：客户端保留原版式，在宿主用捕获数据
生成 PNG 后进入同一 `execute_score` 完成既有结果/错误/JPEG 处理。
Application 不获得 Provider、回调、私人成绩路径或存储 handle。

中心 `TAIKO_CENTER_ROOT` 默认 `/home/sigaer/taiko`，继续支持 `TAIKO_USERDATA_DIR`；
它们定位既有资源/数据，不迁移数据。中心 SQL 连接参数与两条 SELECT 原文未改，
prepare 只读绑定；SQL 事务结束后才等待文件锁。未修改数据库或 Viewer。

## 授权与兼容性

中心按用户明确选择保留旧规则：他查时由当前选中账号的 visible 授权整个 u0，
不新增逐成员可见性规则。有序成员、profile、slot、source 或绑定观察变化时拒绝旧结果。
客户端仍经中心私人读取权威检查，包括内存缓存/304；不引入离线私人成绩兜底。
其发送复核比较完整绑定观察，并再次执行中心授权读取；新读到的数据不替换已捕获的渲染输入。
原客户端 tinfo 内的八处旧发送检查随 handler 移除，统一由新的授权发送边界覆盖；
其他命令及其复核不变，不能再把“35 处调用数不变”作为本阶段结论。

保留两端既有模糊匹配差异、reply/direct、错误和图片版式。tinfo 不需要 history，
PreparedPrivateInput.history 保持 None；缺历史不会引发额外读取/写入。
中心 native u0 保留首次/热请求/成员更新物化、dependency hash、current/history
序列化与时间语义。客户端仍使用远程派生结果，不把 sourceView 冒充原生 dependency hash。

`publication.py`、`reader.py`、`merged_materialization.py`、`backup.py`、`bridge.py`、
`daily.py` 及包初始化逐字节迁移；`merged_read` 只改历史解析 import，
`merge_reference` 只将原公共资源根定位改为宿主配置。所有函数/类 AST 不变。
历史解析源码逐字节迁入。exclusive/shared、stage/publish、恢复、原子发布、Writer
语义没有重写；既有 shared 恢复仍可能产生基础设施写入。

## 验收

所有执行、构建、安装通过既有 memory/run_qa.sh；只安装隔离 wheel。

| 验证 | 结果 |
| --- | --- |
| 中心实际事件分派 | **115 PASS**：108 parity + 四时点撤权 + 三类旧目标失效 |
| 客户端实际事件分派 | **115 PASS**，相同分支与平台覆盖 |
| 双端 Application 能力审计补充 | 各 **15 PASS**；禁止私人/Writer import 及非公开资源 IO |
| 原公开命令完整宿主回归 | 中心 **78/78**、客户端 **80/80 PASS** |
| 原 u0/PublicationStore 回归 | **60 tests + 5 subtests PASS**，含子进程锁竞争、恢复与旧新摘要比对 |
| 包安装 | 两端 pip check PASS；Core/Contract 实际版本符合各宿主精确约束 |
| 静态归属 | Sakura tinfo 活动入口/Provider 为零；非 tinfo 命令 AST 不变；无反向 Sakura import |

事件测试覆盖 normal、u0 已有、u0 首次、成员变化、profile 变化、缺历史，使用真实
OneBot/QQ 事件、完整冻结 handler 与实际生产尺寸 renderer。正常图片必须包含 hash，
不能让双方同时报错充当成功；比较发送内容、图片 SHA256、异常类型/消息及发送参数。
中心首次 u0 的旧/新图片事件使用两份独立、未物化的合成成员目录。
四个撤权时点为准备前、准备后、渲染后、实际发送前；另比较成员、成员顺序、profile
变化，即使 user_id 相同也拒绝。未宣称跨网络发送与撤权绝对原子，未连接真实 Bot/DB。

冻结旧 handler 的外围绑定获取使用同一真实 Provider，以隔离入口/渲染差异；因此
事件 parity 不是独立旧 SQL/HTTP 授权算法的证明。原中心只读绑定函数和 Provider
规则的源码核对、真实存储回归及独立撤权测试补充这一边界。客户端远程服务使用
合成 HTTP 边界，不宣称重新验证 Viewer 内部实现。

逆序装载测试发现注册归属问题后，入口增加显式 public 依赖，双端六组装载顺序与
各十五项事件/授权/能力检查通过。初次验证还修正了测试工具的重复 load_plugin 用法、
消息段序列化及子进程 main guard；
构建环境补齐 wheel 工具，公共测试补齐既有参考 fixture。这些修正未改存储协议。

## 证据与复现

- `tests/runtime_ownership/`：事件、公共回归、存储和静态审计；README 说明输入及基线。
- `docs/taiko-runtime-ownership-validation.json`：逐项摘要、源码与 wheel hash。
- 完整隔离证据：`/var/tmp/taiko-phase2fe-20261014/evidence/`。
- 事件逐项结果：同目录上一层 `events-center/events.json`、`events-client/events.json`、
  `guard-center/events.json`。保留所有图片 hash，不提交图片或玩家数据。
- 构建/复现脚本：同目录上一层 `build.sh`、`verify.sh`、`public.sh`；运行前用
  `/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh` 包裹。存储可单独运行
  `env/bin/python application/tests/runtime_ownership/storage.py sakura/taiko`。

交付为独立候选；未合并 main、未部署、未重启、未安装生产环境、未读写生产 userdata，
未修改生产 P0 或运行配置。完成后停止。
