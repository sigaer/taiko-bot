# Phase 6.3e.8.5 客户端私有读取与历史

2026-10-12，client 0.2.4，源码轮完成；整个 Phase 6 Gate 仍 IN_PROGRESS。本轮 commit/push 为激活前准备，需要中心 Viewer 0.82.0 及 canonical Source/service grant 就绪。线上中心尚未发布该版本；本轮不启动客户端，也不宣称 online acceptance。

每次私有 current/history GET 都访问中心并完成权限检查；缓存候选只可由精确 ETag 304 确认。缓存以 URL、token SHA、Source、kind 隔离，64项/32MiB总计/4MiB单项/30s TTL，返回对象为调用者所有。错误、无凭据、过期与重定向不提供旧缓存；POST结果不填充权限缓存，磁盘userdata不参与权威读取。HTTP输入/输出32MiB，单读90s、C/H配对180s且最多重试一次。local API private GET只转发调用者自己的Bearer，PUT410。

u0由中心在全成员SH与principal/所有Source证明下合并，标识完整保留Bot principal，包括官方身份尾部下划线；不再本地物化。合并版本覆盖成员向量、绑定/profile选择与公开规则参考。

私有历史请求 `?format=raw-v1`，保留 filename 与捕获的mtime/ctime；这些只用于旧排序语义，不是游玩时间或measurement。u0使用含微秒的合并配方名称，保持原中心 materializer 的时刻。默认SDK旧DTO不变，隐式私有loader拒绝缺少元数据的非空历史。趋势按旧 full/delta/removal profile重建并逐点计算；更新图/B30/当前段位使用一组同版本C/H。更新图保留上一条完整歌曲/dojo状态，段位回退保留反向文件名顺序；查询token在中心读取前后检查撤销。旧本地成绩与原生Hiroba Writer在任何IO前返回410；保留其旧实现作未激活阶段回退，后续全部Writer激活时移除。

实际 guarded suite 最终153通过（2条既有警告，无skip）。冻结oracle为 `adae96ea2976347386d85b416cba9e385710b43d`，AST提取原filesystem函数，测试只使用owned files，覆盖空/单条/多条、full/delta/removed、相同时间、微秒、无效JSON、unknown filename的mtime回退、空/无效_meta.ts、profile/dojo carry，以及趋势日聚合/曲数回退。原算法Core Goldens沿用既有Phase4范围；新趋势聚合测试使用确定性非空计算值隔离数据流，未将其称为新的算法Golden。实际更新图以小型PIL panel输出PNG；B30/段位原生准备函数在渲染边界捕获输入，未冒称完整资源/图片QA。实际owned SQLite用 PRAGMA database_list 验证路径，测试token删除/轮换/映射变化及中心拒绝；HTTP只使用MockTransport，无生产私有读写。

跨仓库受限QA：Source62 +5subtests、pipe12、SQL/HTTP143、TS通过，172.261s/504815616byte采样peak，high/max/OOM0；最后3个本地Writer禁用用例加入后仅重新跑client153，未无故重复未变的Source/Viewer。详细日志、hash、unit/commit/push见Viewer `docs/taiko-domain-extraction/evidence/phase6-client-history-validation.json`。

尚未完成全Writer/P1a、native credential/QQ/token issuer最后接入、Read Model/invalidation、百万冷暖IO/RSS、trusted ops、R固定依赖/停止旧Writer/统一激活、真实online产品smoke。回退：client adae96e（0.2.3）、Source356cd1ef、Viewer834962b；旧实现可从这些Git对象恢复，中心与客户端协议一起回退，不打开旧缓存的错误fallback。

## 6.3e.8.6c 绑定删除与可见性（子步骤 PASS）

2026-10-12，client 0.2.5 源码轮完成。删除绑定改用中心 authenticated GET 与 remove POST，位置只用于解析具体账号 ID；最后一个绑定的确认保存中心已证明的 ID 和现有 TTL，不再读取本地 JSON。给看/不给看调用 visibility POST，中心修改整个 principal 的可见性，不经 upsert 重建绑定或重置 u0。删除当前账号保留客户端原有的后继选择规则；原生 Bot 的选择 profile 保持独立。手动账号删除继续使用既有专用生命周期接口。

中心一次 SQL 事务修改绑定、槽位、选择状态与精确所属 Hiroba 凭据。删除和可见性分别要求显式 service scopes `bind_remove` / `bind_visibility`，旧 `bind_write` 不获得新权限；principal 和全部成员 Source 仍须授权。小型 durable receipt 绑定 actor/grant、意图及操作效果，同 nonce 重试返回当前绑定和原操作结果，不删除后来重新绑定的账号，也不覆盖后来的选择/可见性。客户端最多两次同请求重试，256KiB 流式响应上限，90s 分块检查期限及最长 10s 单次 socket 等待；这不是严格的 90s 进程硬期限。错误状态与重定向不回退本地权限或数据库。

最终 guarded client 181 项通过（153 既有、28 新增，2 条既有警告），局部 TypeScript 和实际 SQL/HTTP 66 项通过。同轮先前未变的凭据/访问控制 78 项通过，合计 144 项 SQL，分属两次 QA，未冒称同一次执行。包含真实 Python SDK/命令 AST 到 owned H3 HTTP、5 个冻结客户端删除选择样例、最后确认、重绑重试、撤权/回滚/ACK loss 与四个 COMMIT 前后真实进程退出。上游、完整 NoneBot 注册、线上产品验收与百万数据性能不在本轮范围。

最终 memory QA 72.334s，250ms 采样峰值 533839872 bytes，child maxRSS 399568KiB，high/max/OOM 均 0；systemd 成功退出。初轮 fixture/TS/SDK guard 失败如实保留；fixture 初始化失败留下的 66 条孤立测试 QQ 行已逐条证明所有权并在 `_test` / 双显式 opt-in 下删除，剩余 0，初始化现在受 finally 清理。中心证据为 `docs/taiko-domain-extraction/evidence/phase6-client-binding-mutation-validation.json`。

本版本需要 Viewer 0.82.0 中心协议激活和显式 service grant，当前只标准 commit/push，不启动客户端。Viewer 仍本地预备，线上 0.81.11 未切换；Source A 9.81.21 未变，运行 R 未同步。Phase 6 / native authority 整轮仍 IN_PROGRESS：客户端 QQ 迁移/token issuer、native Hiroba/QQ、全部 Writer/P1a、Read Model、成本/运维和统一激活仍待完成。回退本子步以 client `47bf5c1` / 0.2.4 与 Viewer `39c2327` 成对恢复，不能恢复旧本地 authority 到已激活中心。

## 6.3e.8.6d 网页成绩 token 中心签发（子步骤 PASS）

2026-10-12，client 0.2.6 源码轮完成。私聊命令从中心读取发送者当前绑定，再提交该 principal 与具体实账号到 `/api/taiko/proxy/bind/score-token`。不使用提及用户/可见他人绑定作为 owner，也不再按账号 ID 查询本地 SQLite 所属。隐藏的自有实账号可签发；u0、manual、他人/失效授权拒绝，错误不泄漏底层诊断。中心响应 `private, no-store`，Vary Authorization/Cookie。

中心捕获 pool/runtime paths，Source EX → principal gate → SQL，事务前后及 COMMIT 前证明完整 caller/grant、全部 Bot binding/选择和普通 owner 的对应 web Source/platform。服务须显式 `score_token_issue`、principal 与全部绑定 Source，provisioning 拒绝省略 principal 的该 scope。中心既有 token 表/48hex 格式与 mask 保留，单次事务旋转；ACK 丢失只在仍持 EX、捕获 pool 的新连接证明精确 token 与 caller/current 后成功。签发请求仅一次，不自动重试，不保存含 token 的 durable receipt；用户再次发送命令明确旋转 token。

没有实际业务调用者的旧本地 bearer helper 在任何 IO 前 410，原本地 token 表作为历史未使用 schema 保留，不从中读写私有授权。其 10 项旧 local-authority 测试被 24 项中心 transport/command/retirement 用例替代；完整 client 195 项（171 保留 +24）及两条既有警告通过。命令 AST 验证私聊、群聊拒绝、隐藏自有、空/manual/u0/中心拒绝及发送者传递；原 parity suite 仍执行其既有 NoneBot module import，但未宣称完整 Bot 启动/adapter QA。

既有绑定 SQL 66 项通过，最终 token 24 项实际 SQL/HTTP +1 项纯 provisioning 策略检查及 TS 通过；与既有绑定合计 90 项 SQL/HTTP +1 项策略，分属两轮；包含 actual Python SDK → owned H3、全成员 service policy、返回前撤权、rollback/lease loss、Source/principal 队列、exact ACK proof/captured pool 替换以及两个 COMMIT 真进程退出。最终 QA 26.613s/471056384byte cgroup 250ms 采样、child maxRSS 361936KiB、high/max/OOM0，systemd 成功清理。初轮转导出 import 失败（150 pass/3 fail）及 test top-level import 绕过 fixture 注册（66 pass/1 file fail）已修正并留档；没有生产数据/凭据复制或写入。

Source A 9.81.21 unchanged，Viewer 0.82 仍本地预备，运行 R/线上 0.81.11/PID 未变，不启动 client 0.2.6。详细日志/hash/commit/remote 见中心 `phase6-client-score-token-validation.json`。QQ 迁移、native Hiroba/QQ、全 Writer/P1a、Read Model/百万成本/运维、固定 R 依赖与统一激活仍待，Gate 6 IN_PROGRESS。回退本步为 client `a8f1b38` /0.2.5 与 Viewer `80c8d3c` 配套源码，禁止恢复旧本地 authority 到已激活中心。
