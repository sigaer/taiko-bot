# Phase 2F-C — Public Catalog Command Ownership Cutover

日期：2026-10-13。状态：**PHASE_2F_C_BLOCKED**。

已完成 `const_query`、`patterns` 的双端入口迁出及有限 parity。`score_cmd` 遵照本轮副作用停止条件保留宿主所有；不授予三个入口全部完成标记。

## 阻断：score_cmd

真实源码调用链如下，未执行刷新或修改它：

- 中心：`score_cmd → compute_score → _get_initial_points → _load_score_json → load_scoreline_data(JSON_PATH) → _ensure_scoreline_dataset_current → rebuild_scoreline_dataset → output_path.write_text`。`JSON_PATH` 与 `UNIFIED_PATH` 都指向 `songs/taiko_goku_onis.json`。
- 客户端：`score_cmd → compute_score → _get_initial_points → _load_score_json` 比较 `song_score.json`、连打资料和曲库的 mtime，缺失或过期时调用 `rebuild_scoreline_dataset(JSON_PATH)`，最终同样 `write_text`。

冷读/缓存失效时可触发这条自动刷新链。把它搬进公共插件违反本轮限制；直接去掉刷新或只喂预计算 fixture 则不能证明既有数据源行为等价。因此 `score_cmd` 的 matcher、handler、计算、配置读取及刷新函数全部保持原字节/AST；没有绕开或改造 Writer。未来若要迁移，必须另行明确这条自动刷新依赖的处理边界，本轮不设计新基础设施。

## 已完成源码归属

扩展同一个 `nonebot-plugin-taiko-song` 到 **0.3.0**，客户端候选包 **0.2.12**。Application **0.5.0**、中心 Core **0.1.1**、客户端 Core **0.1.2**、Contract **0.1.0** 不变。

- `catalog_commands.py`：两个 matcher 和 handler，使用既有发送模块。定数用例复用 `execute_constant`；客户端先执行原公开资源准入。
- `catalog_provider.py`：只读公共曲库、定数与配置资料。定数和分页复用 Application；客户端在投影前保留 Core visibility 筛选，中心保持原 shelf profile。
- `pattern_query.py`：六个纯解析/过滤/抽样 helper，保留原 `set → list` 和 `random.sample` 语义，不自行排序或统一输出。
- `constant_center_renderer.py` / `constant_client_renderer.py`：各自必要的原定数绘制实现。全部绘制函数 AST 与对应旧模块相同；保留两端列、文本、布局及模板回退差异，不创建第二套 QQ/OneBot 发送框架。

Sakura：主插件删除 **284 行**（两个 matcher、两个 handler、六个 helper、三个正则常量及不再使用的 imports），已无消费者的 `utils/const_query.py` 删除 **510 行**，运行源码合计减少 **794 行**。

客户端：主插件删除 **336 行**，专用定数模块删除 **526 行**，运行源码合计减少 **862 行**。其他消费者使用的共享 helper 保留；`score_cmd`、其裸 `查分` 活动查询相邻入口均未改。

两个入口不再有宿主活动实现。中心/客户端各自不同的 renderer 是显式保留的产品展示差异，不强行统一。既有七个公共入口和三个发送模块原字节不变（初始化文件仅增加新模块装载）。

## 有限验收

| 项目 | 中心 | 客户端 |
| --- | --- | --- |
| 真实 NoneBot 分派与自身旧输出 parity | 78 项 PASS | 80 项 PASS |
| `const_query` / `patterns` 宿主 matcher | 各 0 | 各 0 |
| 对应外部 matcher | 各 1 | 各 1 |
| 外部插件总 matcher | 9 | 9 |
| 其他宿主 matcher 声明不变 | 65 | 61 |
| 完整依赖解析 / pip check | PASS | PASS |

覆盖正常、空结果、非法参数、两页及越界、含下架、隐藏曲目过滤、仅下架提示差异、BPM/难度/配置及子串匹配、随机截断、缺模板和缺公开输入。`random.seed(73013)` 与 `PYTHONHASHSEED=0` 固定；比较完整有序消息，不只比较集合。两端真实 PNG 比较编码 SHA256、解码 pixel hash、dimensions、mode，未使用占位图片。

每端包含 **14 项**原七个入口的双平台代表性回归，复用 Phase 2F-B 固定输入及完整期望发送载荷。客户端另有 **2 项**公开资源准入拒绝。每端 **4 项**故意缺失资料的异常会被显式捕获并比较，不把框架吞异常当正常成功。裸 `查分` 不匹配三个相关查询入口；原计分正则/活动入口声明也保持不变，未运行其刷新链。

执行查询时禁止文件写入，SQL、网络与生产路径读取被审计钩子拒绝。两端观察到命令文件写入均为 0。其他宿主插件正常装载；按“函数名+装饰器”核对避免重名 handler 遗漏，剩余主模块函数/类中心 **294**、客户端 **230** 个 AST 不变。安全补丁 helper 与 **35** 个发送前复核调用保持不变，没有新增复核。

全新 `center-env` / `client-env` 安装真实 Application/插件 wheel，客户端另装真实客户端 wheel；使用完整依赖解析，未使用 `--no-deps` 安装。中心按锁定源码布局装载：`CENTER_SOURCE_RUNTIME_PASS / CENTER_WHEEL_NOT_REQUIRED`。逐文件核对已安装代码来源；15 个通用 runtime support 源文件对照 Phase 2E-R manifest 核验。未读取维护者私有环境或生产 `/opt` 依赖。

## 证据、安装顺序和剩余命令

- [汇总、精确版本、wheel/fixture/resource/reference hash](../packages/nonebot-plugin-taiko-song/tests/catalog-acceptance/summary.json)
- [中心结果](../packages/nonebot-plugin-taiko-song/tests/catalog-acceptance/center-dispatch.json)、[客户端结果](../packages/nonebot-plugin-taiko-song/tests/catalog-acceptance/client-dispatch.json)
- [中心依赖锁](../packages/nonebot-plugin-taiko-song/tests/catalog-acceptance/center-lock.txt)、[客户端依赖锁](../packages/nonebot-plugin-taiko-song/tests/catalog-acceptance/client-lock.txt)
- [移除及剩余 matcher 完整清单、授权核对](../packages/nonebot-plugin-taiko-song/tests/catalog-acceptance/scope.json)
- 测试入口：`tests/catalog_dispatch.py`、`tests/catalog_scope.py`；完整独立运行目录、冻结旧源、制品和安装日志：`/var/tmp/taiko-phase2fc-20261013`。所有 QA 经既有 `scripts/memory/run_qa.sh` 隔离执行，不重复 2A–2E 历史矩阵。

候选安装顺序：先提供 Application 0.5.0 和歌曲插件 0.3.0 wheel，再使用匹配的客户端 0.2.12 或 Sakura 移除提交。新插件不能与仍注册这两个 matcher 的旧宿主混用。两宿主各自精确锁 Core；没有 PyPI 发布或生产安装。

剩余宿主所有权包括阻断的 `score_cmd`、B30、tinfo、进度、推荐、段位、机厅、年度、猜歌、管理与私人账号入口；完整名称见 scope 清单。没有迁移私人 Provider、storage、Writer、SQL、sync、daily/history，没有改 Core 公式/Contract/Viewer，没有旧 246 文件候选或 Phase 6。

仅交付上述部分完成候选；未合并 main、部署或重启。完成本轮后停止。
