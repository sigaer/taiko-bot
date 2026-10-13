# Phase 2F-D0 — u0 Merge Kernel Dependency Decoupling

日期：2026-10-13。状态：**PHASE_2F_D0_MERGE_KERNEL_DECOUPLED**。

## 基线与边界

从指定 Taiko `14fc23a`、Sakura `38826aa` 创建独立
`feature/u0-merge-kernel-decoupling` 分支。D1 阻断证据为 `28f3d4d` / `1601c5a`。
执行时原 main 已有后续提交及用户 WIP；没有覆盖或吸收这些变化。
没有合并 main、部署、重启、生产安装或生产 userdata 读写。

Application 0.6.0 新增 `taiko_application.merged_bind`，复用既有发行包。
公开插件 0.3.1 仅调整 Application 精确依赖；客户端 0.2.13 仅更新该插件依赖。
中心 Core 0.1.1、客户端 Core 0.1.2、Contract 0.1.0 声明不变。
没有迁移任何命令入口、持久化 Writer、SQL、sync 或 daily。

## 直接依赖与最小移除清单

| 模块 | 原依赖 | 本轮结果 |
| --- | --- | --- |
| `plugins.utils.merged_bind` | 内嵌纯计算/模型；combo 文件与缓存；snapshot_history；动态调用存储 Writer | 模型及纯函数委托 Application；combo 读取委托 host `taiko_store.merge_reference`；绑定入口和历史文件读取保留 |
| `taiko_store.merged_read` | 从 Sakura merged_bind 导入 payload/key 合并与 combo loader | 直接导入 Application；从 host reference 取 combo；保留 snapshot_history 时间解析和 PublicationError |
| `taiko_store.merged_materialization` | 动态从 Sakura merged_bind 导入模型、异常与 payload 内核 | 直接导入 Application；其余验证、锁、发布流程不变 |

移除 Sakura 内嵌的 4 个模型/异常类，以及 `build_virtual_user_id`、
`merge_song_records`、`build_achievement_from_songs`、`_merge_payloads`、
`_merge_snapshot_histories`、`_normalize_removed_key`、`_song_key`、
`_is_song_record_better`、`_song_accuracy`、`_song_update_key`、`_safe_int`、
`_current_payload_time` 的计算实现，统一由 Application 维护。
原调用名称保留别名或薄委托，以保持现有宿主调用和异常捕获。
移除两个 store 模块对 `plugins.utils.merged_bind` 的 import。
没有移除公开命令或私人命令；没有复制新的 Writer。

combo loader/cache 只迁到 Sakura 自己的 `taiko_store.merge_reference`；路径仍为
同一 `songs/song_data.json`，解析、失败回退和进程缓存规则不变。
Application 接收只读 `Mapping[(song_no, level), combo]` 与显式 `clock`。
clock 在原先生成时间戳的位置调用，保留本地时间、排序及历史覆盖行为。
同分记录保留先到成员；成员顺序仍影响完全同分选择和 dependency hash，
没有擅自把成员向量排序成集合。输入 payload 不被修改。

## 差异验收

- 冻结 oracle 为 `38826aa` 原文件，SHA256
  `4e9948d7eb697335688d81ed6c663f684ba42bbb47f8e04d5c33470f6115e4df`。
  原源码随 Application 测试保存；只替换 combo 输入与测试时钟，实际执行旧算法。
- 纯内核 **59/59 PASS**：重复记录、完全同分、成员反序、排序、非法记录、
  空输入、缺失历史、profile 来源/回退、身份校验、缺失成员模型与错误消息。
  比较完整结果并检查输入不变；不把正常用例的双边异常当作成功。
- 既有 u0 **34/34 PASS**，PublicationStore **21/21 PASS**；包括真实子进程
  shared/exclusive 锁竞争、发布中断恢复、增量历史、热请求与不合法请求。
- 新完整调用链 **5/5 PASS**：4 组成员顺序/profile 组合各执行首次发布、
  成员更新、重复请求；旧、新 dependency hash 和全部 current/history 字节摘要一致。
  另验证真实缺失成员抛出同一公开异常别名，slot 顺序及消息不变。
- 合计 **119 tests + 5 subtests PASS**，最终 pytest 14.25 秒。
- 实际 wheel 在独立虚拟环境中执行；独立内核重放禁止宿主导入，执行期间禁止
  文件/网络/SQL IO，**PASS**。未使用生产虚拟环境。
- 原九个公开命令：中心 **78/78**、客户端 **80/80 PASS**，覆盖 OneBot/QQ、
  正常与错误状态，执行既有 catalog_dispatch 冻结回归。命令实现源码未改。
- 35 处客户端 `_require_private_send_authority` 检查与整个授权模块字节不变。
  本轮不据此宣称完成私人命令实时撤权迁移。
- PublicationStore、reader、snapshot_history 字节不变；两个 store 调用模块 AST
  仅允许替换 import 和添加 combo/clock 内核参数后，与基线完全一致。
  dependency recipe、序列化、成员向量、exclusive/shared、stage、publish、恢复
  与原子发布实现均未改。

全部执行 QA、安装及构建通过既有 memory/run_qa.sh；数据仅为隔离目录中的合成
fixture。原有测试只调整 cache/clock 的 patch 所属模块，原断言保留。
初次源码路径测试的子进程无法导入未安装的 Application，改用实际安装 wheel 后通过；
新测试曾误用 commit 的 filesystem_times 参数，已修正为既有 stage/publish API。
这些属于测试接线修正，没有修改存储 API。

## 剩余 Writer 依赖

`materialize_merged_bind_userdata` 仍是宿主持久化入口，仍调用
`taiko_store.merged_materialization.materialize`；后者仍持有成员 shared 锁和
输出 exclusive 锁，执行 stage、publish、增量历史及 dependency receipt。
`merged_read` 仍使用宿主 snapshot_history 时间解析；combo 文件/cache 也仍由宿主拥有。
本轮只解除合并计算对 Sakura merged_bind 的反向依赖，不提供新的私人只读授权边界。
**不代表 u0 Writer 已迁出，也不代表 tinfo/B30 已可迁出。完成后停止。**

## 证据与复现

两仓保存 `docs/u0-merge-kernel-validation.json`，记录用例数、源码范围和 wheel hash。
完整临时证据目录：`/var/tmp/taiko-phase2fd0-20261013/evidence/`。
两仓工作树：同目录的 `application/`、`sakura/`。
Application 测试：`packages/taiko-application/tests/merged/`；
Sakura 新调用链测试：`taiko/tests/test_merge_kernel_decoupling.py`。

在安装候选 Application 的环境，以 memory/run_qa.sh 包裹 Python：
运行 Application `tests/merged/test_parity.py`；运行 Sakura
`test_merged_bind.py`、`test_merged_private_read.py`、`test_merged_materialization.py`、
`test_merge_kernel_decoupling.py` 和 `test_publication_store.py`。
`audit_scope.py --application PATH --sakura PATH --output PATH` 重现静态边界审计；
`standalone.py` 在非宿主 cwd 重现禁止 IO 的纯内核检查。
两端 `packages/nonebot-plugin-taiko-song/tests/catalog_dispatch.py` 继续使用既有
合成/public 资源 fixture；完整执行脚本和依赖清单位于上述临时目录。
