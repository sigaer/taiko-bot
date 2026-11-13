# 公共歌曲查询第二阶段：性能与兼容性证据

日期：2026-11-13（Asia/Shanghai）。基线为 `perf/song-query-snapshot` 的 `070442ef19afc1827a79aa542e092c50e27b0994`（Bot 0.23.1、Application 0.9.2）；候选为本分支 Bot 0.24.0，Application、索引实现与匹配语义不变。第一阶段报告和原始数据原样保留。

**当前生产前 Gate：PENDING。** 可选静态 Manifest 与启动预热默认关闭。官方 QQ 三样本 API 成功且用户确认三图各收到一次、正常显示；客户端显示计时和 OneBot 终端实测未完成，事件循环阻塞风险尚待生产验收。没有合并或部署。生产 PID 2886113、启动时间 11:24:19 CST 未变。

## 环境与统计口径

- 同一宿主机：Linux 5.10.0-16-amd64、Python 3.11.4；使用 `/opt/taiko-bot/releases/0.23.0/bin/python` 的依赖环境。核心为已安装 Core 0.1.1，另用仓库固定 Core 0.1.2 完整回归。宿主机 8 个逻辑 CPU（QA 配额 2 CPU）。没有替换 fuzzywuzzy 的纯 Python SequenceMatcher。
- QA 全部经现有 memory runner 串行运行：MemoryHigh 2 GiB、MemoryMax 3 GiB、SwapMax 256 MiB、CPUQuota 200%、15 分钟上限；数据、临时文件及证据使用磁盘目录。未清除系统页缓存，宿主机有正常业务负载。cgroup OOM/oom_kill 均为 0，memory.peak 在当前内核不可读，不编造峰值。
- 实际安装依赖：nonebot2 2.5.0, nonebot-adapter-qq 1.7.3, nonebot-adapter-onebot 2.4.6, httpx 0.28.1, httpcore 1.0.9, Pillow 11.3.0, fuzzywuzzy 0.18.0, sakura-taiko-core 0.1.1；版本来自本机 distribution metadata，见 validation.json。
- 同一冻结曲库：歌曲 2,989 条、别名记录 2,071 条；两文件 SHA-256 与第一阶段一致（`647f45530fb0862e7993e193b8da507932aa0b2c0b50ff4d253d00a41ff8ead6`、`1619632c9c51c0b931fedc01d37c4f1a666dc4f66c13258c7dc0076cac9ca3e6`）。
- 延迟为 perf_counter_ns，CPU 为 process_time_ns，P50/P95/P99 为 nearest-rank。文件计数是逻辑调用，不等于物理磁盘 IOPS。RSS/PSS 来自 smaps_rollup，不等于新功能净分配。
- 第一阶段基准、事件循环风险、第二阶段图片管线、真实 QQ API 与客户端显示分别测量。没有把不同阶段 P50 相减当作端到端收益。

## 第一阶段生产前风险补测

使用冻结的 070442e 内核；单请求各 100 次，8/32 并发各 12 批。并发请求延迟从共同释放时间起算，包含等待；CPU 是整批耗时。5 ms 心跳取每批最大调度延迟再计算分位，未混入大量空闲 tick 稀释阻塞。100 次复核分布通过原 store 的到期分支触发，另有一次真实等待 31 秒验证。曲库更新在批次开始前原子替换隔离文件，每次确实变更内容。

单位 ms；单元格 P50 / P95 / P99。并发 12 批的 P99 只是本次观测尾部，不能作为生产 SLA。

| 场景 | 批次 / 请求 | 请求/准备耗时 | 心跳最大延迟 | 进程 CPU（批） |
|---|---:|---:|---:|---:|
| first_load | 100 / 100 | 351.298 / 390.269 / 419.356 | 346.348 / 385.339 / 414.431 | 351.326 / 390.072 / 419.238 |
| warm | 100 / 100 | 0.243 / 0.359 / 0.384 | 0.342 / 0.475 / 0.500 | 0.266 / 0.388 / 0.419 |
| verify_30s_branch | 100 / 100 | 18.825 / 31.553 / 33.221 | 13.854 / 26.601 / 28.240 | 18.870 / 31.623 / 33.277 |
| update | 100 / 100 | 333.053 / 411.102 / 476.235 | 328.094 / 406.150 / 471.297 | 333.108 / 411.142 / 476.217 |
| cold_concurrent_8 | 12 / 96 | 300.905 / 389.569 / 390.163 | 295.922 / 385.168 / 385.168 | 300.917 / 390.227 / 390.227 |
| verify_concurrent_8 | 12 / 96 | 12.479 / 12.978 / 13.259 | 7.767 / 8.260 / 8.260 | 12.802 / 13.297 / 13.297 |
| update_concurrent_8 | 12 / 96 | 328.570 / 418.594 / 419.059 | 323.584 / 414.063 / 414.063 | 328.605 / 419.106 / 419.106 |
| prewarm | 100 / 100 | 326.473 / 382.293 / 433.817 | 103.027 / 123.637 / 146.433 | 328.204 / 384.244 / 435.985 |
| after_prewarm | 100 / 100 | 0.269 / 0.325 / 0.403 | 0.367 / 0.434 / 0.541 | 0.293 / 0.354 / 0.438 |
| warm_concurrent_32 | 12 / 384 | 1.643 / 2.860 / 2.987 | 0.997 / 1.080 / 1.080 | 2.999 / 3.076 / 3.076 |
| fuzzy_concurrent_8 | 12 / 96 | 1137.602 / 2032.863 / 2415.964 | 1987.664 / 2410.986 / 2410.986 | 1992.587 / 2415.745 / 2415.745 |

自然 31 秒复核：请求 12.636 ms、CPU 12.684 ms、心跳最大延迟 7.663 ms（n=1，无 P95/P99）。该进程最终 RSS 174.59 MiB、PSS 164.70 MiB；包括重复构建与回放，不是生产常驻大小。

结论：预热后第一个玩家查询已处于稳态，P95 0.325 ms；代价是启动准备 P95 382.293 ms，期间线程仍可因 GIL 产生心跳延迟 P95 123.637 ms。默认关闭的启动 hook 只复用原 get_snapshot，在启动接纳请求前准备；失败保留原惰性恢复。

**仍存在生产风险：** 同步首次加载和更新的心跳 P95 约 385/406 ms；30 秒复核 P95 26.601 ms；8 个模糊请求一批的心跳 P95 2410.986 ms。本阶段没有重写第一阶段、改变模糊算法、移走更新工作或声称无阻塞。生产验收必须明确接受风险或另行授权解决。

## 第二阶段独立管线回放

两版本分别在独立进程执行真实命令解析、原快照查询、brief、deliver 及实际安装的 QQ/OneBot SDK 消息模型。最终保留四组，每个平台每版本冷请求 1 次 + 稳态 500 次，共 2,004 次；真实已授权的 Oni/649 PNG：816×1648、85,957 bytes，SHA-256 `238e29e26d75455743679bd8f85b705669ac60398678e033bcfd01b4898f9748`。Manifest 准备、源文件校验与 HTTPS MockTransport 不在计时窗口内。另有独立完整图片管线并发回放，见下节。

发送器是记录消息的 coroutine，并非 QQ API。`mock_send_dispatch_ns` 只记录本地调度，不作为网络收益；每个请求恰好一条消息。`pre_send` 包含完整本地查询及构造到尝试发送，`total` 额外含本地记录器和结束处理。探针带少量开销；只验证本次单谱面、ID 查询，不推广为全曲库或线上端到端改善。

单位 ms；P50 / P95 / P99。Markdown 一行仅测 SDK 模型构造；完整内容拼接/宽高处理/路径检查包含在 pre_send 内，不另编造可比的局部数字。

| 阶段 | QQ 原路径 | QQ 静态命中 | OneBot 原版本 | OneBot 候选版本 |
|---|---:|---:|---:|---:|
| 搜索与命令 | 0.100 / 0.137 / 0.161 | 0.065 / 0.080 / 0.104 | 0.081 / 0.100 / 0.114 | 0.080 / 0.101 / 0.132 |
| 歌曲 brief | 0.023 / 0.040 / 0.042 | 0.020 / 0.023 / 0.032 | 0.021 / 0.023 / 0.032 | 0.021 / 0.026 / 0.036 |
| PNG read | 0.017 / 0.020 / 0.021 | 0 次 | 0.013 / 0.015 / 0.019 | 0.013 / 0.017 / 0.020 |
| 临时缓存写入 | 0.214 / 0.304 / 0.340 | 0 次 | 0 次 | 0 次 |
| Markdown SDK 模型 | 0.012 / 0.012 / 0.014 | 0.005 / 0.008 / 0.009 | 0 次 | 0 次 |
| 本地 pre_send | 0.710 / 0.974 / 1.026 | 0.359 / 0.409 / 0.466 | 0.376 / 0.430 / 0.526 | 0.377 / 0.480 / 0.646 |
| 本地 total | 0.753 / 1.016 / 1.068 | 0.378 / 0.432 / 0.491 | 0.402 / 0.459 / 0.557 | 0.403 / 0.514 / 0.692 |
| CPU | 0.752 / 1.012 / 1.054 | 0.377 / 0.432 / 0.482 | 0.401 / 0.459 / 0.557 | 0.403 / 0.514 / 0.691 |

| 指标 | QQ 原路径 | QQ 静态命中 | OneBot 原版本 | OneBot 候选版本 |
|---|---:|---:|---:|---:|
| PNG 读取 / 请求 | 1 | 0 | 1 | 1 |
| 随机图片写入 / 请求 | 1 | 0 | 0 | 0 |
| 实际 QQ API 调用 | 0 | 0 | 0 | 0 |
| 冷请求 total ms | 385.746 (n=1) | 403.843 (n=1) | 433.071 (n=1) | 427.227 (n=1) |
| 回放前 RSS MiB | 106.32 | 106.73 | 106.30 | 106.78 |
| 回放后 RSS MiB | 138.49 | 138.93 | 138.58 | 139.20 |
| 回放后 PSS MiB | 124.68 | 124.69 | 124.71 | 124.83 |

静态命中稳态 PNG/随机文件次数由 1/1 变为 0/0 有直接证据。本机完整 pre_send 的分位有上表观测值；搜索和 brief 没有算法变化，二者的小幅差异可能来自调度、冷热或探针，不归因为静态 URL。OneBot 无速度改善结论。冷请求被索引初始化主导，不声称更快。

QQ 回放后进程 RSS 候选比基线约 +0.44 MiB、PSS 约 +0.005 MiB；不是隔离的净保留内存，也不是 13,140 项 Manifest 的内存预测。运行期仅保留有界不可变 map/entry，不保留完整原始 JSON 树和查询结果缓存。

## 第二阶段完整图片管线并发

独立进程、快照/SDK 预热后，每版本 12 批 × 8 并发 = 96 请求；使用与单请求相同的真实样本和实际 deliver，含 brief、PNG/缓存路径或 Manifest/Markdown。发送仅为本地 recording coroutine，不访问 QQ API。逻辑 PNG open/随机写入计数为独立探针，96 个请求均产生一条 Markdown。

单位 ms；P50 / P95 / P99。完成延迟从批次共同释放时间起算，包含等待和本地异步 dispatch；pre_send 从每个 coroutine 开始运行算起，故两者不是相同口径。n=12 批，P99 不代表生产 SLA。

| 指标 | 原路径 | 静态命中 |
|---|---:|---:|
| 含队列完成耗时 | 6.128 / 6.777 / 6.817 | 3.358 / 4.774 / 4.799 |
| 本地 pre_send | 0.719 / 0.880 / 0.943 | 0.375 / 0.582 / 1.890 |
| 整批 CPU | 6.203 / 6.824 / 6.824 | 3.383 / 4.823 / 4.823 |
| 整批心跳最大延迟 | 1.114 / 1.761 / 1.761 | 0.451 / 1.083 / 1.083 |
| PNG / 随机写入总次数 | 96 / 96 | 0 / 0 |
| 输出消息总数 | 96 | 96 |

本次静态组 pre_send P99 1.890 ms 高于原组 0.943 ms，尽管 P50/P95 更低；保留这个尾部，不将一次小样本数据描述为所有分位均改善。原/候选回放后 RSS 分别约 132.51/132.50 MiB，进程内存近似，没有据此宣称内存下降。

## Manifest 元数据规模补测

这是纯合成元数据压力测试，没有发布或宣称验证了全库 13,140 个 URL。分别构造 1 / 13,140 项，禁用远程和图片 I/O；每种 30 次冷加载、30 次稳态、30 次 30 秒复核分支，5 ms 心跳。JSON/Python 分配追踪另开一遍，不混入计时。

单位 ms；P50 / P95 / P99。

| 条目数 | 冷加载 | 稳态 lookup | 未变化内容复核 | 冷加载心跳最大延迟 | 复核心跳最大延迟 |
|---|---:|---:|---:|---:|---:|
| 1 | 0.778 / 1.399 / 1.407 | 0.519 / 0.758 / 0.792 | 0.678 / 0.922 / 0.957 | 0.879 / 0.964 / 0.994 | 0.776 / 1.046 / 1.058 |
| 13140 | 270.100 / 446.026 / 447.178 | 0.516 / 0.789 / 0.789 | 23.633 / 40.807 / 41.018 | 265.170 / 441.099 / 442.242 | 18.680 / 35.863 / 36.082 |

当前实现已让字节不变且 lease 有效的复核只读两份元数据并核对 SHA-256，不重复 JSON 解析或重建 map。13,140 项索引净保留 Python 分配约 9.76 MiB；进程 RSS 28.64→72.68 MiB 包括构造、重复加载及 allocator 保留，不能当作索引净大小。n=30 的 P99 是本次最大值。

**新增规模风险仍保留：** 13,140 项冷解析/实际换代同步执行，冷加载心跳 P95 441.099 ms；未变化内容复核也有 P95 35.863 ms 心跳延迟。本次单谱面管线收益不能外推为全量 Manifest 的冷启动或更新收益。尚未实现后台 Manifest 刷新、全量资源预热或正式续期任务，默认关闭，须在生产前验收处理。

## 资源与发布审计

本地 13,140 张 PNG 合计 1,045,548,643 bytes；五目录计数分别为 3,115 / 3,135 / 3,152 / 3,083 / 655。逐图宽高/hash 只抽查歌曲 649、354 的前四难度，未宣称全库图像都已通过发布校验。用户当前授权为「全都允许」；授权与来源追踪、逐项 hash policy 仍是发布前置条件。完整结构与续期边界见 [design.md](design.md)。

现有资源下载来自 taiko.wiki，缺图可以从本地 TJA 生成；OSS 同步使用可变键 `fumen/<difficulty>/<id>.png`。已对 Viewer Manifest 和 chart-image 做真实 HTTPS GET，均为 200，后者 SHA-256 与本地样本一致、Cache-Control 为 public max-age=300。它们不是新的内容版本 URL；没有验证 OSS ACL/实际 HTTPS endpoint，不声称 OSS 已满足静态发布要求。

离线发布器只复制显式 hash 授权条目，验证 PNG，再对最终内容哈希 HTTPS URL 完整 GET；资源可读后才原子切换本地 Manifest。不可达、内容不符、损坏、无授权都不能进入新 Manifest。查询热路径不发 HEAD/GET。健康 lease 默认 300 秒、最大 900 秒，不能保证 lease 内绝不发生网络故障；到期回退。正式续期、可用性监控与旧哈希保留未部署。

## 兼容性与回归

- Core 0.1.1 的中心端搜索/读音/快照测试：69 passed、21 deselected（排除只适用客户端/未安装新 Core 的命令用例），QA `qa-870907fbc7af`。
- Core 0.1.2 原全部搜索、读音、可见性、快照 + 新 Manifest/发送测试 + 原全局图片/QQ probe 回归：200 passed、20 subtests passed，QA `qa-6ca9832c77a8`。保留真实曲库逐项差分、阶段开关、更新、损坏恢复、请求上下文及并发原测试。
- Manifest/发送定向回归最终 59 项通过（QA `qa-005cf29cdc51`，新增深层 JSON 损坏后失效与恢复补测）；模块在未初始化 NoneBot 时仍可供纯图片构造器导入，存在 driver 时正常注册预热；实际安装 SDK 的中心/客户端矩阵覆盖普通/模糊提示、静态命中无 PNG、缺项回退、发送前构造失败、默认关闭、OneBot 不查 Manifest、超时/未知结果发送次数为一，以及 40034128 的既有中心主动规则。
- 本地独立 TLS HTTPServer 实际执行发布 GET + 同 URL 首次/重复读取，校验完全相同的 SHA-256；删除源图后仍可读取已发布副本。server/socket/thread 在 finally 关闭并确认退出。它证明 HTTPS 协议，不代表原生 QQ 客户端缓存。
- Manifest 覆盖路径/URL 白名单、symlink、未授权不复制、坏图、缺失、远端 404/重定向/type/hash 错误、过期、撤权、损坏恢复、发布中断保留旧文件、8 并发首次读取，以及 4 读者与原子发布者交错切换。歌曲快照加载失败保留旧版本的逻辑没有改动；静态授权过期则严格失效，不沿用旧授权。

## 真实 QQ API 与客户端验收

复用 `/var/tmp/taiko-qq-delivery-private/config.json` 的旧测试 Bot/群/管理员，凭据与标识不进入报告。使用独立 SDK worker，未启动网关/服务/业务插件，认证缓存与生产隔离。旧配置的主动权限未声明，实测仅使用同群管理员新发 `/qqprobe C` 的被动 msg_id，最多三条，每次间隔至少 25 秒。已过期事件不复用，未知结果停止，不补发。

已将一张授权谱面放到既有测试目录的专用 `song-query-phase2` 子目录并完成真实 HTTPS 内容校验；仅隔离运行目录有 policy/Manifest，不切换生产引用。测试图与基线随机图仅在此自有命名空间，实测窗口结束后显式清理，原缓存与清理定时器不变。

真实 API 样本见 [live-qq.json](live-qq.json)，QA `qa-e517fbb66cd2`。三次全为 HTTP 200 / acknowledged，发消息请求各一次。用户明确反馈「各收到一次、正常显示」；设备型号和显示计时未提供。这个结论只覆盖三条测试消息，不外推为并发/长期投递保证。

单位 ms；n=1/场景，不计算 P95/P99，也不主张 API 性能改善。基线首次认证有独立获取 token 成本；两个静态请求复用认证缓存，因此三次 API 墙钟不能直接比较为功能收益。

| 场景 | 搜索/命令 | brief | Markdown 模型 | 发送前本地 | PNG / 随机写入 | API 总计 | 其中 HTTP | 认证 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| before | 19.664 | 0.047 | 0.027 | 27.842 | 1 / 1 | 2289.349 | 2059.112 | 220.069 |
| static-first | 19.306 | 0.049 | 0.026 | 20.249 | 0 / 0 | 1808.277 | 1795.954 | 0.013 |
| static-repeat | 18.893 | 0.047 | 0.024 | 19.605 | 0 / 0 | 2361.590 | 2353.838 | 0.013 |

触发间隔约 30 秒，所以真实样本的搜索包含原曲库内容复核成本；没有把它混入 500 次离线稳态回放。两个静态样本由同一有效 Manifest、同一 SHA-256 生成同一个 URL；实际发送路径 PNG/随机写入均为 0。三次 SDK 请求均使用新连接；完整 trace 保存在脱敏 JSON，不含标识、凭据或消息体。

原生客户端首次/重复显示时间均为 **NOT_MEASURED**（null），没有用 GET 时长或 API ACK 代替。用户确认暂时没有 OneBot 测试端，OneBot 仅有实际 SDK 隔离回放。QQ 显示兼容性得到本轮用户观测，整体生产 Gate 仍受未测项和阻塞风险限制。

用户观测确认后，隔离测试 worker 已退出；专用公网子目录和隔离 Manifest 已删除，QA `qa-2f1fa3da45db`。没有修改旧图片清理定时器或 30 分钟缓存。

| 验收项 | 当前状态 |
|---|---|
| 静态命中 PNG/随机文件均为 0 | 隔离回放 PASS |
| 原有匹配/提示/难度/两端差异 | 回归 PASS |
| HTTPS 发布顺序与 hash | 本地 TLS + 专用公网样本 PASS |
| 官方 QQ 三样本 API/显示兼容性 | PASS：每条一次 ACK，用户确认每图各收到一次、正常显示 |
| 客户端同 URL 首次/重复显示时间 | NOT_MEASURED |
| OneBot 隔离终端收图 | PENDING：用户确认暂无测试端；SDK 回放已通过 |
| 曲库与全量 Manifest 同步加载/更新、模糊匹配阻塞风险 | 已量化，生产验收待定 |
| 生产合并/部署/服务修改 | 未执行 |

## 复现与证据索引

所有命令从本分支工作树运行，使用 memory QA runner。环境变量、平台 ID 与认证配置不在命令中。离线 fixture 仅复制冻结公共曲库和已授权样本。基线须 checkout 到独立工作树，不以当前 main 代替。

```bash
QA=/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh
PY=/opt/taiko-bot/releases/0.23.0/bin/python
SRC=/var/tmp/taiko-bot-song-query
BASE=/var/tmp/taiko-song-query-phase1-reference
CAT=/var/tmp/taiko-song-query-evidence/catalog
OUT=/var/tmp/taiko-song-query-phase2-evidence
bash "$QA" "$PY" scripts/performance/song_query_phase2/loop_risk.py --source "$BASE" --candidate "$SRC" --fixture "$CAT" --output "$OUT/loop-risk.json"
# prepare 使用新的空 fixture；四次 replay 各独立进程，平台 qq/onebot，variant before/after。
bash "$QA" "$PY" scripts/performance/song_query_phase2/pipeline.py prepare --source "$SRC" --fixture "$OUT/fixture" --catalog "$CAT"
bash "$QA" "$PY" scripts/performance/song_query_phase2/pipeline.py replay --source "$BASE" --fixture "$OUT/fixture" --platform qq --variant before --output "$OUT/before-qq.json"
bash "$QA" "$PY" scripts/performance/song_query_phase2/pipeline.py replay --source "$SRC" --fixture "$OUT/fixture" --platform qq --variant after --output "$OUT/after-qq.json"
# OneBot 同理。时间超过 900 秒需先在隔离目录重新验证、续期 Manifest：
bash "$QA" "$PY" scripts/performance/song_query_phase2/pipeline.py refresh --source "$SRC" --fixture "$OUT/fixture"
bash "$QA" "$PY" scripts/performance/song_query/run.py tests --fixture "$CAT" --core-source "$SRC/packages/sakura-taiko-core/core" --tests tests/test_song_search.py tests/test_song_phonetics.py tests/test_song_visibility.py tests/test_song_catalog_snapshot.py tests/test_static_fumens.py tests/test_static_fumen_delivery.py tests/test_qq_image_delivery.py tests/performance/test_qq_delivery_probe.py
# 完整图片管线并发回放；before/after 分别选择相应源码
bash "$QA" "$PY" scripts/performance/song_query_phase2/concurrent_pipeline.py --source "$SRC" --fixture "$OUT/fixture" --variant after --output "$OUT/concurrent-after.json"
# 规模测试（仅合成元数据）
bash "$QA" "$PY" scripts/performance/song_query_phase2/manifest_scale.py --source "$SRC" --output "$OUT/manifest-scale.json"
```

| 证据 | QA run |
|---|---|
| [loop-risk.json](loop-risk.json) | qa-efb2c30970ad |
| [before-qq.json](before-qq.json) | qa-2a3799f5feb3 |
| [after-qq.json](after-qq.json) | qa-e9876ec29161 |
| [before-onebot.json](before-onebot.json) | qa-a925f4b3fed7 |
| [after-onebot.json](after-onebot.json) | qa-16ef6ccfc470 |
| [resource-audit.json](resource-audit.json) | qa-299c770d8c4a |
| 真实测试 URL 离线发布 | qa-a157936fe735 |
| 最终完整回归/图片策略/probe：200 + 20 subtests | qa-6ca9832c77a8 |
| [manifest-scale.json](manifest-scale.json) | qa-066bbd477784 |
| [live-qq.json](live-qq.json) | qa-e517fbb66cd2 |
| [validation.json](validation.json)：范围、默认关闭、原基准未动、生产 PID 与清理 | qa-eedbff79679e |
| [test-resources.json](test-resources.json)：完整测试资源记录 | qa-6ca9832c77a8 |
| [concurrent-before.json](concurrent-before.json) / [concurrent-after.json](concurrent-after.json) | qa-d85d52c70ce4 / qa-bba9ec01f31a |
| 静态路径最终定向回归 59 项 | qa-005cf29cdc51 |
| 专用测试资源清理 | qa-2f1fa3da45db |

文件 SHA-256 与大小清单见 [artifacts.json](artifacts.json)。原始数字不包含凭据、群号、用户消息、实际资源文件或私有数据库。QA vault 保留更完整的资源/进程退出证据。
