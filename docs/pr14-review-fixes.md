# PR #14：P2 审阅修复

基线 Taiko `c563acd` / Sakura `e764a50`；仍在 `feature/taiko-runtime-ownership`。
状态：**PR14_P2_FIXES_VALIDATED**。没有合并、部署或重启。

## 统计识别与遗留所有权

Sakura `taiko/nonebot_plugin_method_calls/taiko_commands.py` 按明确的 owner 模块解析
已加载的 matcher 对象；保留 MRO 对临时 matcher 类型/实例的支持。九个公开 matcher 与
`music_info` 从 Taiko 内部模块取得，其他旧命令继续从 `plugins.taiko` 取得。
不以宽泛的 `taiko_bot.*` 前缀或命令文本认领其他 Bot。注册表不主动 import/register 插件，
不永久缓存启动早期不完整的集合。canonical/display/platform/group_id 提取与旧 spec 不变。

恢复范围：是什么歌、别名、歌在哪、在什么位置、位置 ID、难度 ID 查谱、物量、定数、
配置、tinfo。三个位置 matcher 继续汇入同一个 canonical「位置」，而显示文案保持原差异。
保留旧 OneBot @其他账号不计数规则；没有改变查询/授权业务语义。

**未来仍需迁出 Sakura 的遗留所有权**：本统计 registry、extractor、recorder 及
`taiko_commands_v2` 聚合接线仍在 Sakura。此次只适配真实 matcher 所有者，不是统计子系统
已经迁出的声明。Taiko 不反向 import 这些模块，不将其定义为永久性 Taiko adapter。
`store.py`、SQL schema 和既有统计数据完全未改；只恢复后续调用的分类。

## 测试归属与前后结果

完整载入合成公共 fixture 后，旧测试确认 **6 failed / 31 passed**：

- removed `generate_score_image`：1；
- removed `_load_font` 导致三条布局断言失败：3；
- removed `_extract_music_info_command_match`：1；
- removed `plugins.taiko.music_info`：1。

四条成绩卡行为断言迁至 Taiko `tests/runtime_ownership/test_score_presentation.py`：
使用实际 `center.presentation.prepare_score_presentation` 验证先读曲名再收集成绩，
使用实际 Application `ScoreInfoRenderer` 验证字体间距与 V2 常数标签。输入改为显式 current，
不再伪造旧 user_id 文件读取入口。仍属 Sakura 的两条辅助函数测试保留。
另验证真实 QQ event 的 mention_user 不污染 tinfo 参数，matcher 只注册一次。
Sakura 官方兼容测试同时核对新 owner 与旧模块不再有 tinfo matcher/handler。

最终仅运行关联范围：

| 范围 | 结果 |
| --- | --- |
| Sakura drawinfo / official compatibility / extractor / rollup | **38 PASS，86 subtests PASS** |
| Taiko 新 owner 成绩卡/QQ mention/唯一注册 | **5 PASS** |
| 中心九个公开命令 × OneBot/QQ，真实统计 postprocessor | **18 个事件 = 18 条分类入队记录** |
| 中心既有 tinfo guard-smoke：图片/文字/错误、撤权、陈旧目标 | **15 PASS** |
| public 优先、player 优先、批量装载 | **3 PASS**，九公开 + 一 tinfo |

聚合测试直接调用原 `_build_rollup_rows`，22 次成功 recorder 调用（十个迁入 matcher +
一个保留的 update，双平台）分别得到 hour/day total 22、每平台 11、位置 6、tinfo 2；
每次只 enqueue 一条，异常调用不追加，分类 bucket 不重复。generic/无效记录不进入 v2。
80 个迁入 matcher 子用例比较完整字段，覆盖 class、instance、临时子类与双平台。

## 隔离、复现与边界

全部通过既有 `scripts/memory/run_qa.sh`。环境为候选 center-env，Core 0.1.1、Contract
0.1.0、Application 0.7.1；仅给 QA 环境补齐 pytest、aiomysql、宿主已有 apscheduler 依赖。
没有运行 driver startup、连接 SQL/网络或读取生产 userdata。初始 fixture 接线曾被 IO guard
拦截公共资料/通用配置路径，随后仅将公共资料和白名单入口指向隔离 fixture；没有放宽 guard。
最终关联测试与事件检查均无禁止 IO。没有重跑大规模业务、存储或图片矩阵。

Sakura 关联测试用原宿主代码和合成公开 catalog；先经 NoneBot manager 装载 public/player，
再 import 遗留宿主，与 pyproject 的装载顺序一致。Taiko owner 测试在另一进程使用已安装包，
以 `--import-mode=importlib --confcutdir=tests/runtime_ownership` 避免客户端 conftest
将中心环境误切到客户端源码。测试装载接线修正没有改变运行代码。

命令入口：Sakura `tests/test_drawinfo.py`、`tests/test_official_command_compat.py`、
`nonebot_plugin_method_calls/tests/{test_extractor,test_rollups}.py`；Taiko
`tests/runtime_ownership/test_score_presentation.py`。实时 postprocessor 检查通过 Sakura
`tests/run_method_calls_runtime_smoke.py TAIKO_CHECKOUT --host center --work OWNED --assets PUBLIC`
调用既有公开事件 smoke；tinfo 沿用 `events.py --guard-smoke`。

原始隔离 runner、公共 fixture 接线和日志：`/var/tmp/taiko-pr14-review/`；
[验收摘要与日志 hash](pr14-review-validation.json)。源码审计确认 Taiko 运行代码/Application、
Sakura 非统计业务、Writer、storage、SQL schema、Core/Contract 均未改。原 Phase 2F-E
完整验收证据未覆盖或删除。本轮 P2 修复未发现剩余代码阻断；既有 Taiko 配套 PR 创建权限
问题不在此次修复范围，Sakura PR #14 保持 Draft。
