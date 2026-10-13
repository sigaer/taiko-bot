# Taiko Application Extraction — Phase 2E-R

日期：2026-10-13。状态：**PHASE_2E_DUAL_HOST_INTEGRATION_COMPLETE**。
本轮解除 Phase 2E 的隔离装载、中心事件分派、真实绘图链路及授权时序阻断，完成后停止。

## 精确基线与安装

| 项目 | 本轮结果 |
| --- | --- |
| Application | **0.5.0**，实现及依赖声明与 `152137a` 相同 |
| 中心源码 | Sakura `c8ed8c11088152ed2190bc422337a293f02fd9f0`，未修改 |
| 客户端 | 基于 taiko-bot `152137a` 的 **0.2.9** 功能分支候选 |
| Core | 中心 **0.1.1**；客户端 **0.1.2**，分别精确锁定 |
| Python Contract | 两端均 **0.1.0** |
| 验证环境 | Python **3.11.4**、Pillow **11.3.0**、NoneBot **2.5.0**、OneBot adapter **2.4.6** |
| 生产 Viewer | **0.81.12**，未变更 |

**CENTER_SOURCE_RUNTIME_PASS**；**CENTER_WHEEL_NOT_REQUIRED**。

中心从锁定 revision 导出 `taiko/` 源码到独立目录，另从同一 revision 导出 `runtime_memory` 和 `qq_official_runtime`。284 个中心 Python 文件及 15 个 support Python 文件逐一核对原提交字节。中心按已有源码布局装载；Application、Core、Contract 及必要框架依赖来自新建 venv 的实际安装，不宣称整个中心 wheel 安装成功。

中心新环境补齐实际导入需要的 QQ adapter、PyMySQL 和 Uvicorn。测试记录了实际模块来源；没有使用生产 `/opt`、原 Sakura 工作目录或维护者已有虚拟环境。历史硬编码文件输入在测试外围映射到隔离公开 fixture，既有中心源码保持不变。

客户端最终从空 venv 完整解析、安装 **taiko-bot 0.2.9 + Application 0.5.0 + Core 0.1.2 + Contract 0.1.0**。两端 `pip check` 均通过，没有使用 `--no-deps`。精确宿主锁见功能分支的 `packages/taiko-application/tests/recovery/locks/`；完整安装日志、报告及 freeze 保存在 [evidence 目录](/var/tmp/taiko-phase2er-20261013/evidence)。

## 实际事件与绘图链路

| 验证 | 结果 |
| --- | --- |
| 中心六类真实 NoneBot matcher/rule/handler 分派 | **23/23 PASS** |
| 客户端真实分派，含四类私有命令的 16 个发送前拒绝用例 | **39/39 PASS** |
| 中心 B30、tinfo：真实 Provider → Application → renderer → 消息 | **2/2 PASS** |
| 客户端 B30、tinfo：真实 Provider → Application → renderer → 消息 | **2/2 PASS** |
| 客户端发送前授权时序：五种失效 × 两条真实绘图链路 | **10/10 PASS** |

事件测试使用合成 OneBot 消息和模拟发送接口，保留真实 matcher 注册、rule 和 handler；排除其他产品的 matcher。正常、空结果、非法参数、缺失输入及权限拒绝均检查实际响应。执行 postprocessor 捕获框架异常，审计钩子记录禁止 IO 的尝试，不能把被吞掉的异常算作通过。初始权限拒绝时不进入 Application、不读成绩、不绘图或发送私人图片。

分派测试的图片 Provider 使用固定 PNG；**真实链路验证另行执行，未用固定 PNG 或固定评级代替 renderer/计算**。使用同一公开曲库向量、30 条合成成绩、固定时钟、42 个固定 SHA256 图片/字体资源和隔离缓存；完整 draw_dress 也实际运行。资源集合在既有 41 个公开资源之外补入公开的 `dress/common/line/line_290.png`，来源及 hash 已记录，不提交图片包或玩家数据。

客户端仅替换最外围 HTTP 响应，保留真实 Developer API 身份解析、成绩 Provider 和缓存代码。中心使用隔离文件输入及模拟授权数据库响应。v2 catalog 注入公开输入，计算函数保持真实；历史输入为空。本轮没有迁移或改写 daily/history、Writer。

新旧命令分别运行自己的完整冻结 B30/tinfo handler 函数体，旧参考仅移除注册 decorator 后装入真实 matcher；共享同一真实绘图环境。中心已抽取 renderer 的旧新等价证据沿用 Phase 2B，本轮比较命令调用和实际绘图链路，不另造一套旧 renderer。

| 宿主 / 命令 | PNG 尺寸 / mode | 与自身旧命令比较 |
| --- | --- | --- |
| 中心 B30，显式 `v1` | 1080×3030 / RGBA | PNG hash、pixel hash、最终消息载荷一致 |
| 中心 tinfo | 1060×3110 / RGBA | 同上 |
| 客户端 B30，既有 v1 | 1080×3030 / RGBA | 同上 |
| 客户端 tinfo | 2884×1220 / RGBA | 同上 |

比较包括真实 JPEG 编码后的消息图片、文字和发送选择。两端 tinfo 布局及 B30 图片存在原有差异，未强行统一 profile。中心默认 v2 的完整绘图不在这次代表性链路重测范围；已有 Phase 2E 业务矩阵保留。

## 两项最小修复

1. **发送前授权缺口。** 原客户端在真实 B30 绘图完成后，即使模拟中心撤销授权，仍发送图片；失败日志保留。新增宿主 `taiko_runtime/application_delivery.py`，仅由 B30、tinfo、进度、推荐四类私有命令调用。发送前重新执行原有授权解析，核对身份、账号、来源和虚拟账号属性；任何失败或变化都丢弃旧结果，返回安全提示。公开曲目/定数命令不增加私有读取。
2. **安装后的资源根。** `b30_render`、`b30_single`、`drawinfo`、`draw_dress` 原先使用模块位置推导根目录，wheel 安装后落到 `site-packages`。现改为既有 `get_settings().root_dir`，不新增配置系统。客户端最终测试没有修改模块资源全局值或函数默认参数，直接使用实际 `TAIKO_BOT_ROOT`。四个模块的全部函数/类 AST 不变。

正常客户端请求在原 Provider 顺序末尾增加 binding 与 current 两次授权读取，图片和消息结果保持一致。这是安全修复的显式行为差量。时序测试在真实绘图后分别模拟 binding 403、成绩 403、超时、切换身份、非法身份，B30/tinfo 均不发送旧图片；成绩 403 还验证 current 缓存项被丢弃。缓存不被视为授权证明。本轮不宣称发送平台网络传输期间存在跨系统原子授权 lease。

除上述四个私有 handler 和新增发送包装外，客户端其余 **253** 个顶层函数/类 AST 不变。Application 源码、包依赖声明、`taiko_bot` 数据 Provider/缓存实现、Core/Contract 均未修改。没有重跑全部 86+111 个旧业务用例；新增及修改调用点使用本轮针对性回归。

## 证据、去重与后续安装顺序

- [最终审计及四条链路完整 hash](/var/tmp/taiko-phase2er-20261013/evidence/final-audit.json)
- [中心分派](/var/tmp/taiko-phase2er-20261013/evidence/center-dispatch.json)、[客户端分派](/var/tmp/taiko-phase2er-20261013/evidence/client-dispatch.json)
- [中心真实链路](/var/tmp/taiko-phase2er-20261013/evidence/center-chain.json)、[中心旧命令参考](/var/tmp/taiko-phase2er-20261013/evidence/center-reference-chain.json)
- [客户端真实链路](/var/tmp/taiko-phase2er-20261013/evidence/client-chain.json)、[客户端旧命令参考](/var/tmp/taiko-phase2er-20261013/evidence/client-reference-chain.json)
- [修复前泄露复现](/var/tmp/taiko-phase2er-20261013/evidence/client-revocation-before.log)、[修复后授权撤销](/var/tmp/taiko-phase2er-20261013/evidence/client-revocation.json)；同目录包含 `client-score403`、`client-timeout`、`client-identity`、`client-invalid-identity` JSON。
- [可复现测试、资源与源码 provenance、完整版本锁](/var/tmp/taiko-phase2er-20261013/application/packages/taiko-application/tests/recovery/README.md)

六类活动 command usecase 仍只有同一份 `taiko_application.commands`。旧命令仅作为冻结测试参考；没有新增第二套业务实现。客户端原 renderer、数据 Provider、平台适配及其他非本阶段命令仍活动，属于明确保留边界，本轮没有待移除的重复 command usecase，也不以此宣布完整 Sakura 去太鼓化。

未来跨仓集成顺序为：先提供 Application 0.5.0 制品，再以中心 Core 0.1.1 安装到中心源码候选，客户端则安装 0.2.9 并精确保留 Core 0.1.2。Contract 都是 0.1.0；不要将客户端根项目安装进中心环境。本轮没有实施 main 合并或生产安装。

客户端 wheel：`/var/tmp/taiko-phase2er-20261013/wheels/taiko_bot-0.2.9-py3-none-any.whl`。
SHA256：`4bd6e94142918c8ee3ee2a5064d7fa631caeb231b8b00578e65ff8558a329c11`。wheel、已安装文件与提交候选源代码字节一致。

最终组合 QA 经现有 `scripts/memory/run_qa.sh` 执行，exit **0**；63.343 秒，最大子进程 RSS **307,908 KiB**。这是进程统计，不是 cgroup memory.peak。新环境安装、构建和针对性测试均经隔离 wrapper，未绕过 guard。

**本轮没有未解决的验收阻断。** Sakura 原工作区 WIP 与生产目录未改；没有合并 main、部署、重启、修改生产依赖、SQL schema、storage、Writer、sync、daily/history 或 Viewer。没有合入 246 文件迁出候选，没有恢复 Phase 6 或启动 Phase 2F。旧 Phase 2E BLOCKED 报告保留为历史记录，本报告记录解除结果。
