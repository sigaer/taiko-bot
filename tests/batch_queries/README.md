# 查询展示与曲库管理批量归属验收

基线 Taiko cb7a8c1 / Sakura 4d6beda；候选 taiko-bot 0.10.0。
在既有 `runtime.player` 注册中心 9、客户端 7 个入口，既有 public 9 个入口不变。
客户端原本没有查称号与加称号，本次不增加。

| 入口 | 中心 | 客户端 |
|---|---|---|
| quick_actions_panel | 已迁移 | 已迁移 |
| song_rank | 已迁移 | 已迁移 |
| summary | 已迁移 | 已迁移 |
| twso | 已迁移 | 已迁移 |
| city_arcade_query | 已迁移 | 已迁移 |
| tsearch_switch | 已迁移 | 已迁移 |
| song_title_query | 已迁移 | 原无入口 |
| custom_title_add | 已迁移 | 原无入口 |
| tset_alias | 已迁移 | 已迁移 |

## 运行

双端独立 wheel 环境、冻结 checkout（含 plugins）、已有公开素材、合成隔离目录：

```sh
python tests/batch_queries/events.py --host center --baseline /isolated/baseline-center \
  --work /isolated/query-center --assets /isolated/public-assets --application /isolated/taiko
# client 使用客户端 Core 环境和冻结客户端代码。
# --edges：参数/API/文件失败与总结缓存冷、热、绑定变化。
# --datasets：中心称号 SQL 创建、重复、冷却与失败回滚。
# --mode security：真实 OneBot/QQ 分派、完整目标复核、失败发送、统计与查分边界。
```

所有脚本经 memory/run_qa.sh 串行运行。禁用网络与生产路径；SQL 写入使用真实磁盘
SQLite 事务适配原 MySQL 语句，显式 mutation opt-in 并检查 SELECT DATABASE() 为
`taiko_ownership_test`。这不是生产 MySQL 集成测试；逐条比较旧新 SQL、事务与持久化结果。
不重复完整 Core/Application/Storage 验收。

冻结 handler 来自旧源码，替换外部 API、身份与文件路径边界。正常图片必须成功，
比较消息、尺寸及 SHA256；总结复用的装扮函数先断言与旧函数 AST 一致。
旧计算入口通过已验证的记录接口提供合成数据。新 renderer 禁止私人文件、SQL、网络访问。

## 数据与交付边界

- query_access 复用 TinfoHostProvider / PreparedPrivateInput / AuthorizedDelivery；
  twso 使用捕获的成绩（含重复记录聚合），summary 捕获中心 ctime 或客户端请求时间。
- summary_host 执行原 PNG 缓存读写及公开输入准备；renderer 仅使用显式输入。
  u0 PNG 增加授权目标与图片摘要 sidecar，成员、顺序、profile 或绑定变化使缓存失效；
  不改变既有 PNG 格式、Writer 或 PublicationStore 协议。
- 查询称号的可选私人昵称先捕获并在交付时复核；未绑定仍展示原“鼓手”回退。
- management_access 共用曲库查询与过滤，保留中心/客户端上下架差异。
  原数据库、别名文件、开关及日志格式/写入顺序不变，中心审计失败仍按原规则处理。
- 保留中心 QQ 的管理权限语义及客户端 tsearch 的原 OneBot 管理员权限边界。
  不把客户端 QQ 不支持的开关调用误计为成功调用。
- twso 仅匹配裸“查分”，带参数交给已迁移 score_cmd；真实合并分派验证单响应单统计。
- Sakura 旧入口、独占渲染/地图/活动/称号查询源码删除；共享展示/更新/CLI 仍需的实现保留。

最终验收日志与确定性结果在 evidence/；详细保留消费者见 Sakura 迁移记录。

## 本次结果

- 正常冻结行为：中心 30 / 客户端 26；图片尺寸与 SHA256 一致。
- 参数、API、文件失败、缓存：中心 43 / 客户端 29；称号事务 8 项。
- 授权与统计：中心 110 / 客户端 104；IO 守卫违规 0。
- 单测中心 104 / 客户端 24；统计 subtest 264。
- 六种加载顺序、双端完整宿主加载、既有命令代表性回归 204 项通过。
- Sakura 业务源码净减少 4,266 行，客户端旧业务源码净减少 2,508 行。
- 无阻断、无未迁移的既有入口；未部署、重启或读取生产私人数据。
