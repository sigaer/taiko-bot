# 服务端归属迁移（0.13.0）

基线：Taiko `f2f1b89`（0.12.0），Sakura `6cc94e4`（9.82.15）。本次只迁移源码及发布配置，不部署、重启或迁移运行数据。

## 入口与所有者

| 原 Sakura 入口 | Taiko 可执行入口 |
| --- | --- |
| `taiko/server.py` | `taiko-public-api` / `python -m taiko_bot.services.public_api` |
| `scripts/sync_dispatch_server.py` | `taiko-sync-dispatch` / `python -m taiko_bot.services.sync_dispatch_server` |
| `scripts/source_mutation_cli.py` | `taiko-source-mutation` / `python -m taiko_bot.cli.source_mutation_cli` |
| `scripts/account_sync_cli.py` | `taiko-account-sync` / `python -m taiko_bot.cli.account_sync_cli` |
| `scripts/hiroba_credential_cli.py` | `taiko-hiroba-credentials` / `python -m taiko_bot.cli.hiroba_credential_cli` |
| `scripts/sync_hiroba.py` | `taiko-sync-hiroba` / `python -m taiko_bot.cli.sync_hiroba` |
| `scripts/qq_migration_cli.py` | `taiko-qq-migration` / `python -m taiko_bot.cli.qq_migration_cli` |

Source、公开成绩 Token、Viewer 私有授权、绑定查询/变更、QQ 迁移、Hiroba、更新及 daily/history 使用 `taiko_bot.runtime.player.center` 中的共同实现。补齐原 Bot 迁移未带出的服务函数，不新增 Writer、schema 或存储协议。`taiko_store` 未修改。

`taiko_bot.local_api` 是自部署 Bot 的本地代理接口；旧公开 API 和同步分发协议仍为独立服务，没有合并路由。公开 API 的 `/api/song_data`、`/api/token`、`/api/public-score/by-token` 和同步服务的 HTTP 语义、退役路由响应、压缩、限额及超时保持原样。

## 安装和配置（尚未执行生产操作）

在中心专用 Python 3.11 环境安装 `taiko-bot[center]==0.13.0`。不要混用 client 的 Core 版本。以上命令可从 checkout 或 wheel 执行；工作目录继续为 `/home/sigaer/taiko`，或显式使用同等运行目录。

共享 `runtime_memory` 1.1.0 仍由 Sakura 根目录维护，Miku、maimaiDX、Taiko 均有实际消费者。它不是太鼓私有库。本轮没有复制该源码到 Taiko，也未改缓存策略。按该共享库的安装约定，将已有版本化 artifact `/opt/python-memory-runtime/1.1.0/runtime_memory` 安装到服务虚拟环境，或在虚拟环境的 `.pth` 中登记其父目录。中心计算适配器直接导入该库，不再自行注入 `sys.path`。安装验收使用独立测试虚拟环境登记的同版通用 artifact，不使用 Sakura checkout。

部署模板位于 `deploy/services/`，示例解释器 `/opt/taiko-bot/bin/python` 需指向上述环境。模板保留运行工作目录，不创建或搬移 userdata。主要配置：

- `TAIKO_RUNTIME_ROOT`：独立服务的曲目、配置和渲染资源根；模板为 `/home/sigaer/taiko`。Bot 仍优先采用既有 NoneBot 配置。
- `TAIKO_CENTER_ROOT`：既有中心曲目/常数配置根；默认仍为 `/home/sigaer/taiko`。
- `TAIKO_USERDATA_DIR`、`TAIKO_ACCOUNT_CACHE_DIR`：保留现有 userdata 和私有渲染缓存目录。
- `TAIKO_RUNTIME_ENV_FILE`：既有 root 所有且禁止 group/other 访问的环境文件，默认 `/etc/taiko-runtime.env`。DB、Hiroba 加密参数及 Token 目录/冷却路径沿用既有变量，不提交真实值。
- 分发服务继续使用 `TAIKO_SYNC_RECEIVER_HOST/PORT/NAME/MAX_BODY_BYTES/ZSTD_LEVEL`；Wahlap 继续支持 `TAIKO_WAHLAP_CONFIG_PATH`。

私有 CLI 仍从 stdin 接收有界 JSON，凭据不得放入 argv；原 alarm、错误封装及 SQL 超时不变。未来运行配置切换时，调用方应改用表中模块/console 入口；本次没有修改 Viewer 或正在运行的调用方。不存在永久 `server.py` 或 `scripts/*` 转发壳。

仓库中 `taiko_admin_backup.cron` 仍调用原备份任务，无本轮迁出服务入口依赖。没有修改实际 cron。`storage_maintenance.py` 和 service 保留 Sakura，因为其规则实际涉及 PJSK、Sekai、Minecraft、VSIX；没有改变这些清理规则。素材、备份 CLI、年度汇总、growth_compute、merged_read 等剩余工具没有另行迁移，它们对本轮共享模块的消费改为 Taiko 所有者导入。

## 验证

全部执行在隔离工作树、受内存限制的 QA 单元和 `/var/tmp` 合成目录。文件、网络、SQL guard 阻止生产玩家文件、真实 Token、Hiroba 凭据、数据库和 OSS 访问。真实 HTTP 监听仅绑定临时 loopback 端口，测试结束关闭进程/线程。

- 服务迁移测试：139 passed，43 subtests passed；同一测试目录复制到仓库外，使用安装 wheel 的 `python -I -m pytest` 再验通过。
- 真实 handler 的冻结对照覆盖公共 HTTP、错误/限额、Token、配置写入字节、zstd 字节、Source 冷热更新、授权撤销、写入计数、迟到 SQL 失败、锁释放、并发、PNG SHA256、Hiroba 实际解析/同步/冷却/失败恢复、history/daily、备份恢复及收据重试。只替换远端传输、SQL 边界和需要合成的计算输入；成功分支明确断言成功与持久化结果。
- SQL 记录验证 `FOR UPDATE`、事务、重授权及收据操作；32 个删除的生产 Python 文件中 205 个函数/类完成 AST 对照，除运行根路径选择和所有者导入外，业务主体一致。SQL 字面量、锁和 Writer 顺序未变。
- wheel：9 个独立导入、2 个真实服务启动与 HTTP、5 个 CLI 检查；没有 Sakura 路径和 Bot 注册副作用。两环境 `pip check` 通过。
- Bot 代表回归：center/client 各 public 18、lifecycle 46；不重跑完整历史矩阵或未修改的 Core、Application、Storage 全套测试。
- Sakura 留存年度快照消费者：6 passed；其余历史测试保留并修正 owner/动态加载路径，native SQL 子进程 fixture 仍在原测试体系中。

**真实 MySQL 集成未验证**：环境未提供 `mysqld`/`mariadbd` 可执行文件。本轮采用模拟 SQL 验收，未宣称生产发布验收通过。真实 MySQL 专有锁、`FOR UPDATE`、故障恢复仍需在独立临时实例完成发布前验证。没有据此删除任何测试或连接生产数据库。

## 删除清单

Sakura 删除 32 个生产 Python 文件，共 5,056 行；扣除留存消费者适配增加的源码后，Python 生产源码净减少 5,051 行（不含测试和文档）。完整文件/行数清单见 [server-ownership-deletions.json](validation/server-ownership-deletions.json)，函数及保护范围对照见 [server-ownership-audit.json](validation/server-ownership-audit.json)。历史有效测试随 owner 迁入 `tests/server/`，冻结样本保留，未以删除测试取得通过。

本轮结束于源码集成，不启动素材/剩余工具清理或生产部署。
