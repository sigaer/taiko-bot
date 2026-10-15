# 账号与数据生命周期归属（0.11.0）

基线：Taiko e37e07e / Sakura 3b08986。中心 28、客户端 27 个既有入口归入
`taiko_bot.runtime.player.entry`，不增加插件包。中心独有 `game_login_qr` 不在客户端注册。

| 业务 | 入口 |
| --- | --- |
| 绑定与身份 | qq_migration_code、bind_qq、bind_qq_prompt、bind、bind_confirm、bind_switch、bind_hiroba、hiroba_update、bind_remove、bind_remove_confirm、show_bind、unshow_bind |
| 手动账号 | manual_create、manual_rename、manual_claim_code、manual_claim、manual_detach、manual_delete、manual_delete_confirm、manual_score_upsert、manual_score_get、manual_score_delete、manual_score_delete_confirm |
| 更新与令牌 | update、update_typo、public_score_token、developer_userdata、game_login_qr（仅中心） |

每个 profile 使用 identity_cluster、manual_cluster、update_cluster 和 lifecycle_host。
绑定事务、Hiroba 凭据操作、Source 发布调用及更新图的依赖闭包由 Taiko 维护。
原 SQL、Source 锁、提交恢复、历史与 daily archive 算法未改；Application 不接收 Writer。

`lifecycle_authority` 复用 TinfoHostProvider 的完整绑定观察与 AuthorizedDelivery；没有另一套
成绩授权或绑定存储。确认会话关联执行者和完整绑定目标，拒绝过期确认、成员/顺序/profile/
source/visible/u0 变化。手动操作按执行者串行，创建使用已有 API 的 requestId 字段。
客户端更新结果在缓存写入前检查完整授权及返回 taikoId。开发者数据在文件发送与失败预览前
重新验证同一 token/目标。Hiroba 更新拒绝把其他人的 mention 当成自己的更新目标。

保留两端原正则、提示和自动更新差异。统计由 Sakura 现有 recorder 维护，新增入口逐一登记；
历史 update_typo 的宽匹配规则保持不变，仅实际命中拼写变体时计数，避免静默探测重复计数。

## 验证和边界

所有执行位于隔离 worktree、venv、/var/tmp fixture，网络及生产路径访问有审计阻断。
真实 NoneBot OneBot/QQ 分派；冻结旧 handler/helper 与新实现比较文字、SQL/API 结果、图片。
正常成功路径要求真实结果，不能以双方报错通过。

- 双端绑定称号验证、完整目标变化、QQ 私聊迁移验证码/合并/幂等回执、Hiroba 绑定与更新。
- 双端手动创建、改名、认领码、认领及重放、解绑、确认删除、成绩录入/查看/删除；过期、
  跨执行者确认、u0、撤权、失败发送、重复事件、合成服务事务失败。
- 中心实际 native update → getUserData → save_userdata → PublicationStore，验证首次 current/
  history/daily、冷却无请求、增量历史及上游失败无新发布；客户端真实代理解码与图片一致。
- 中心真实更新图 1628×1055，SHA256
  `b9f17304e2197bd790902cf3c42013dff7336411876f16309d2798d079695ab8` 与冻结实现相同。
- 双端 Token 私聊签发、轮换、撤销、u0 拒绝及发送前目标变化；开发者文件/预览成功和撤销；
  中心 QR 成功图片一致。没有新增客户端 QR。
- 55 个旧入口清零；新增入口各一份；完整宿主和不同装载顺序、统计字段与重复过滤验证。
- 九个公开命令、tinfo、推荐、进度、B30、趋势、个人展示有限回归；未重跑全量历史存储验收。
- 56 个迁入的锁/事务/发布相关定义与冻结源码 AST 相同（部署根目录配置除外）。

SQL 测试使用磁盘 SQLite 适配器，GET_LOCK/RELEASE_LOCK 为模拟；**没有真实 MySQL 联调**。
手动账号继续调用现有服务，其服务端 Writer/历史/成就重算未重写；本次验证为实际 HTTP 客户端
和隔离合成事务边界，不声称重验 Viewer 服务端内部实现。Hiroba 登录发现使用合成凭据边界，
随后运行真实 native SQL/Source 调用。所有账号、token、图片资料均为合成数据。

精简日志见 [validation/lifecycle-20261015.txt](validation/lifecycle-20261015.txt)。原始运行日志在
`/var/tmp/taiko-lifecycle-20261015`。事件 harness 为 `tests/lifecycle/events.py`，接受
`--host --mode --baseline --work --assets --application`；baseline 是对应基线插件目录的冻结副本。
模式包括 parity/security/identity/data/updates/registration/hiroba/migration。使用已有内存隔离 QA
wrapper 执行；生产路径和网络拒绝断言必须保持。真实 MySQL child 仅保留为未来显式隔离联调入口，
此次没有运行，仍要求测试数据库后缀和 mutation opt-in。

Sakura 保留的服务/CLI 共享依赖及删除量记录在该仓的 `taiko/docs/lifecycle-ownership.md`。
本次不部署、不重启，不进入互动内容模块。
