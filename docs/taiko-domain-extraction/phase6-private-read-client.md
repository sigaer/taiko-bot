# Phase 6.3e.8.5 客户端私有读取与历史

2026-10-12，client 0.2.4，源码轮完成；整个 Phase 6 Gate 仍 IN_PROGRESS。本轮 commit/push 为激活前准备，需要中心 Viewer 0.82.0 及 canonical Source/service grant 就绪。线上中心尚未发布该版本；本轮不启动客户端，也不宣称 online acceptance。

每次私有 current/history GET 都访问中心并完成权限检查；缓存候选只可由精确 ETag 304 确认。缓存以 URL、token SHA、Source、kind 隔离，64项/32MiB总计/4MiB单项/30s TTL，返回对象为调用者所有。错误、无凭据、过期与重定向不提供旧缓存；POST结果不填充权限缓存，磁盘userdata不参与权威读取。HTTP输入/输出32MiB，单读90s、C/H配对180s且最多重试一次。local API private GET只转发调用者自己的Bearer，PUT410。

u0由中心在全成员SH与principal/所有Source证明下合并，标识完整保留Bot principal，包括官方身份尾部下划线；不再本地物化。合并版本覆盖成员向量、绑定/profile选择与公开规则参考。

私有历史请求 `?format=raw-v1`，保留 filename 与捕获的mtime/ctime；这些只用于旧排序语义，不是游玩时间或measurement。u0使用含微秒的合并配方名称，保持原中心 materializer 的时刻。默认SDK旧DTO不变，隐式私有loader拒绝缺少元数据的非空历史。趋势按旧 full/delta/removal profile重建并逐点计算；更新图/B30/当前段位使用一组同版本C/H。更新图保留上一条完整歌曲/dojo状态，段位回退保留反向文件名顺序；查询token在中心读取前后检查撤销。旧本地成绩与原生Hiroba Writer在任何IO前返回410；保留其旧实现作未激活阶段回退，后续全部Writer激活时移除。

实际 guarded suite 最终153通过（2条既有警告，无skip）。冻结oracle为 `adae96ea2976347386d85b416cba9e385710b43d`，AST提取原filesystem函数，测试只使用owned files，覆盖空/单条/多条、full/delta/removed、相同时间、微秒、无效JSON、unknown filename的mtime回退、空/无效_meta.ts、profile/dojo carry，以及趋势日聚合/曲数回退。原算法Core Goldens沿用既有Phase4范围；新趋势聚合测试使用确定性非空计算值隔离数据流，未将其称为新的算法Golden。实际更新图以小型PIL panel输出PNG；B30/段位原生准备函数在渲染边界捕获输入，未冒称完整资源/图片QA。实际owned SQLite用 PRAGMA database_list 验证路径，测试token删除/轮换/映射变化及中心拒绝；HTTP只使用MockTransport，无生产私有读写。

跨仓库受限QA：Source62 +5subtests、pipe12、SQL/HTTP143、TS通过，172.261s/504815616byte采样peak，high/max/OOM0；最后3个本地Writer禁用用例加入后仅重新跑client153，未无故重复未变的Source/Viewer。详细日志、hash、unit/commit/push见Viewer `docs/taiko-domain-extraction/evidence/phase6-client-history-validation.json`。

尚未完成全Writer/P1a、native credential/QQ/token issuer最后接入、Read Model/invalidation、百万冷暖IO/RSS、trusted ops、R固定依赖/停止旧Writer/统一激活、真实online产品smoke。回退：client adae96e（0.2.3）、Source356cd1ef、Viewer834962b；旧实现可从这些Git对象恢复，中心与客户端协议一起回退，不打开旧缓存的错误fallback。
