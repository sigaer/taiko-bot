# Phase 2F-D1 — tinfo Host Provider Migration

日期：2026-10-13。状态：**PHASE_2F_D1_TINFO_HOST_PROVIDER_COMPLETE**。

本轮源码接线范围是冻结参考对应的**中心 Sakura tinfo**，以及独立 Taiko 仓库的 Application 数据输入接口。客户端私人 tinfo 保持原实现，不计作已迁移。未进入 B30、progress、recommendation、Writer 迁移；没有修改 PublicationStore、storage 协议、SQL 或 Viewer，没有部署、重启、生产安装或生产 userdata 读取。

基线：Taiko `a7ddece`（D0.6，包含 D0.5 `8299f54`，Application 0.6.0），Sakura `e90fafd`（D0）。隔离分支为 `feature/tinfo-host-provider`；工作树为 `/var/tmp/taiko-phase2fd1-host-20261013/{application,sakura}`。历史 D1 阻断分支及原工作区 WIP 没有吸收或覆盖。

## 授权决策

本轮用户明确选择：**保留旧中心规则；当前账号 visible 授权整个 u0**。因此没有采用 D0.5 文档中的逐成员可见性策略。自查仍允许；他查以当前选中真实账号的 visible 决定整次查询；manual 成员、成员顺序及 profile 选择继续按中心规则处理。

取得数据及交付前重新读取同一完整绑定快照：包括实际行身份、slot、source、选中状态、visible 和 virtual 选择。成员、顺序、profile 或可见性变化均丢弃旧结果，不能只比较虚拟 ID。binding observation 是请求内一致性标识，不是授权票据；dependency hash 也不提供权限。

旧、新静态绑定下的业务结果作严格 parity。撤权场景是新增拒绝边界，不能宣称与旧中心缺少发送复核的行为相等。已经交付的消息无法撤回；发送前验证与远程平台交付不是原子事务。

## 实现与最小移除清单

| 位置 | 变更 |
| --- | --- |
| `plugins/utils/tinfo_provider.py` | 真实 Host Provider：复用 `_read(..., locked=False)` 和 `_entry` 取得绑定快照，验证所选账号可见性，调用既有 materializer，捕获 canonical current 与 provenance。SQL 连接及存储 lease 都留在宿主。 |
| `plugins/taiko.py:music_info_handle` | 改为 `prepare()` → PreparedPrivateInput → 公共查询/展示输入准备 → `execute_score(PreparedScoreCommand)` → 授权交付。移除该入口的旧绑定 resolver 和 ScorePorts callback 接线，不再凭 user_id 调用成绩 loader。matcher、rule 与命令解析入口仍在宿主。 |
| `plugins/utils/drawinfo.py:prepare_score_presentation` | 消费本次 current 的独立 JSON 投影，准备曲库、定数、v2 与公开模板输入；不读取用户路径。使用现有 ScoreInfoRenderer，未重写图片布局或 Core 公式。旧 generate_score_image 函数体保留且未改，供冻结比较/既有兼容入口使用。 |
| `taiko_application.private_input` | 已发行目录中的数据 DTO：authorized target、current、optional history、provenance；嵌套数据复制并冻结。读取失败用数据形式延迟映射，保留“无歌曲/格式错误”先于成绩渲染错误的顺序。没有 Writer、store、userdata 路径或 resolver callback 字段。 |
| `commands.prepared_score` / `execute_score` | 新的数据输入分支，只接收 DTO、匹配选择与公开展示 Context。执行既有 renderer 和 JPEG 转换，返回既有 CommandResult。原 ScorePorts 分支仍兼容其他既有调用，本次 tinfo 不再使用。 |
| `AuthorizedDelivery` | tinfo 专用宿主发送 facade，在 send/带内容的 finish 及被动发送失败后重新验证，覆盖可能进入 QQ 主动回退的时点；准备失败的私人错误也经过复核。未改共享平台适配器。 |

复用现有 Application 发行体系，版本升为 **0.7.0**。公开插件 **0.3.2**、客户端包 **0.2.14** 只更新对应精确依赖；客户端私人命令源码不变。Core 中心 0.1.1 / 客户端 0.1.2、Contract 0.1.0 不变，没有新包或服务/API。

PreparedPrivateInput 不携带文件路径。公开图片/字体资源路径仅存在于既有展示 Context 中；它不含 userdata 路径，也不含回调。Application 的隔离约束是“不再取得私人数据、不调用 Writer”，不是禁止既有图片 renderer 读取公开资源。DTO 是代码所有权边界，不是可以让不可信 Python 代码安全运行的沙箱。

## 物化、capture 与历史

中心 u0 preparation 仍调用 `materialize_merged_bind_userdata` → 既有 `merged_materialization.materialize`。不改变其首次、增量、热请求、profile、时间与 receipt 行为。请求内绝不 adopt 未托管成员。

物化返回后，Provider 按排序 ID 重新取得成员 shared leases，再取得输出 shared lease。核对既有 `native-u0-incremental-v1` dependency recipe（原始有序成员 publication 向量、principal、profile、`merge_rule_revision()`）与输出 manifest 的 dependencyHash。它是既有 receipt 的读侧验证，没有新 hash 协议或修改 Writer。

不一致时，先释放全部 leases，再回到 preparation，最多两轮。Provider 的后续读取/复核受 120 秒请求 deadline 约束，单次新取锁最多 30 秒；materializer 自身继续使用其既有 admission/超时。没有持有输出 shared 锁调用 materializer。SQL 读取事务在等待文件锁前结束。

托管 current 从 captured canonical object 解码，正常非托管账号仍允许既有 legacy reader；不以兼容路径绕过 canonical 校验。复制后退出 lease，再进入 Application。normal 的读取异常延迟到需图片的分支映射；不因无关 current 缺失使文字分支失败。

tinfo **不消费 history**，所以此 Provider 输出 `history=None`、`history_view=None`，不会为展示额外读取私人历史。u0 materializer 内部仍会按原规则维护历史；这不是 history 接口迁移或 B30 的 current/history 配对验收。PublicationStore 构造、锁及恢复的既有文件系统副作用仍存在，不宣称查询物理零写入。

## 验收方法与结果

测试使用真实结构的合成 SQL 行和自有临时 publication。执行现有 SQL 读取函数，fake cursor 拒绝非 SELECT 及 FOR UPDATE；未连接数据库。执行真实 materializer、PublicationStore、canonical reader、成绩展示准备与 ScoreInfoRenderer。公开 catalog/v2 获取与平台发送替换为 fixture；不替换匹配分支、Core 计算、图片布局、合并或发布算法。

旧 tinfo 使用 D0.6 已冻结的完整 `music_info_handle` 与 fuzzy/JPEG 函数体，继续核对 SHA256；D0 绑定 resolver 完整函数另行冻结，只有其数据获取边界由 fixture 提供。新路径执行本轮实际 handler 函数体。两者避开 Bot 包初始化与注册副作用。普通、首次 u0 的新旧路径使用独立目录，不能靠旧路径先物化使新路径跳过首次准备。

| 验收 | 结果 |
| --- | --- |
| normal / u0 首次 / u0 已有 / 成员变化 / profile 变化 / 缺历史 × 10 分支 | **60/60 PASS**；18 个图片结果、30 个文字结果、12 个预期异常 |
| 其余边界、错误与撤权 | **26/26 PASS**；包括四个撤权时点、同 u0 ID 下组合变化、重新准备、物化返回后的单次/持续竞争、发送失败复核、缺 current/成员/模板、损坏 JSON/成绩、renderer 与 JPEG 错误 |
| 实际 wheel 安装 | **86/86 PASS**；不依赖 Application 源码 PYTHONPATH，使用隔离虚拟环境 |
| 原九个公开命令 | 中心 **78/78**、客户端 **80/80 PASS**；OneBot/QQ，冻结 catalog_dispatch |
| 可达 Application 导入图 | **18 个模块**；无 taiko_store、merged_bind、userdata loader、Writer、plugins；传递禁止导入负对照通过 |
| 运行期隔离 | 私人/生产路径、网络、SQL、子进程、Application 写入及宿主重入被禁止；只允许模块加载与公开图片/字体读取。捕获后即使禁用 provider 和 store reader，Application 仍能出图。最终用例违规尝试为 0。 |
| 范围 | 15 个存储/授权/客户端文件字节不变；中心 276 个非目标函数/类、drawinfo 原有 10 个函数/类 AST 不变；客户端命令及授权模块不变，保留 35 处发送前检查 |

比较完整文字、direct/reply、fuzzy prefix、JPEG bytes SHA256、pixel SHA256、尺寸和 mode。异常比较类型与消息；仅归一化 Pillow UnidentifiedImageError 中 BytesIO 的内存地址。正常用例必须产生预期图片/文字，不能以双方异常通过。真实成绩卡不展示 u0 profile，因此 profile 变化不要求凭空改变图片，另核对准备后的 profile 和 dependency receipt。

所有构建、安装和执行 QA 经既有 memory/run_qa.sh，产物在 `/var/tmp`。初轮测试未绕过宿主包初始化，后续加入 guard 时发现并阻止运行配置读取，改为定向加载待测模块；最终审计运行不导入该初始化路径。模板缺失测试曾命中合法 fallback，修正为整个模板资源缺失。重复测试时 cwd 引起 dir_fd 相对路径审计误判，改为隔离 cwd；这些是测试接线修正。没有以这些早期运行替代最终验收。

## 证据与复现

Taiko：`packages/taiko-application/tests/tinfo_host/` 保存冻结 resolver、provenance、完整测试、导入及静态范围审计。原 tinfo 冻结参考仍在 D0.6 实验目录。两仓 `docs/tinfo-host-provider-validation.json` 保存证据摘要及 wheel hash；完整临时证据在 `/var/tmp/taiko-phase2fd1-host-20261013/evidence/`。

从 Viewer 仓库，使用已安装候选 App/Pillow/pytest 的隔离环境：

```sh
bash scripts/memory/run_qa.sh /usr/bin/env \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/var/tmp/taiko-phase2fd1-host-20261013/sakura/taiko \
  TINFO_SAKURA=/var/tmp/taiko-phase2fd1-host-20261013/sakura/taiko \
  TINFO_ASSETS=/var/tmp/taiko-phase2er-20261013/resources \
  /var/tmp/taiko-phase2fd1-host-20261013/env/bin/python -m pytest -q \
  /var/tmp/taiko-phase2fd1-host-20261013/application/packages/taiko-application/tests/tinfo_host/test_boundary.py \
  --basetemp=/var/tmp/taiko-phase2fd1-host-20261013/replay-new
```

重复执行应使用新的 basetemp，或在隔离 cwd 执行以避免清理旧目录时的相对路径审计误判。`audit.py --application PATH --sakura PATH --output PATH` 重现导入/源码范围审计。完整构建、安装及两端公开回归脚本保存在本次临时目录。

此交付不代表客户端私人 tinfo 已迁移、不代表 u0 Writer 已迁出，也不授予 B30、progress、recommendation 或全量 Application 完成。原全局 resolver 和 Writer 为其他宿主入口继续保留。只提交并推送隔离分支，不合并 main；完成后停止。
