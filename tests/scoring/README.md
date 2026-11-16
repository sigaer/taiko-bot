# 分数计算归属验收

基线：Taiko 1afe6ea / Sakura 557f50e；候选 taiko-bot 0.9.0。

`events.py` 在两个独立依赖环境中加载发行 wheel，分派真实 OneBot/QQ 事件。
`--baseline` 指向冻结 checkout 的 taiko 根目录（含 plugins），`--work` 必须为隔离目录；
`--application` 指向本仓，用于已有合成 fixture 和源码归属测试。
公开字体/素材沿用既有验收资产。禁止网络、数据库连接和生产路径读取。

```sh
python tests/scoring/events.py --host center --baseline /isolated/baseline-center \
  --work /isolated/score-center --assets /isolated/public-assets --application /isolated/taiko
# host=client 使用独立客户端 Core 环境和冻结客户端源码。
# 加 --datasets：比较真实 Host 冷/热/更新/缺失重建、写入次数和文件 SHA256。
# 加 --mode security：真实统计 postprocessor、中心完整授权目标复核、失败发送撤权。
```

通过 memory/run_qa.sh 串行运行；不执行完整 Core/Application/Storage 验收。
冻结提取只替换路径与外部依赖边界，不改旧命令、计算或缓存规则。
成功用例显式断言总分、目标分，以及中心稳定分 953000 / 冲分 958000，
避免新旧同时报错被视为业务成功。

## 归属与边界

- `runtime.player.scoring` 在既有 player 插件注册双端 score_line_cmd、score_cmd；
  score_estimate_cmd 仅中心注册。保留原正则、priority=5、block=True。
- Host 的 score_handlers/score_data 保留双端解析、查询与错误差异；
  中心 Rating 目标使用原 Core 算法。Application 和 Core 未修改。
- 中心复用既有 recommendation_support.score_line 的公开数据集写入；
  客户端迁入原公开数据集构建。保留原输出格式、mtime 和 lru_cache 条件，
  包括查分进程内缓存和客户端热索引不重新检查源文件的旧行为。
- 中心估分只使用 PreparedPrivateInput.current；Host 构造既有 estimator profile，
  Core 计算阶段禁止文件/网络 IO。AuthorizedDelivery 复核完整绑定和 u0 目标。
- 旧客户端 score_line.py、旧 handler 与私有分值 loader 已删除。
  中心遗留共享数据集与估分 record API 的实际消费者见 Sakura 归属记录。

原始参数对照、数据集写入、授权、加载和代表性回归日志保留在 evidence/。

## 0.25.2 查分修复

中心查分现在复用分数线的同曲版本解析和修订缓存，不再保留独立的进程生命周期分值缓存。
例如别名“合成器”解析到 ID 191，而分值在同曲 ID 1266 时，仍可读取相应难度的分值。
数据集或来源更新会在下一次查询生效；来源缺失时与分数线一致报错。
上文冻结验收记录描述迁移时行为，数据集对照脚本已显式记录这一预期差异。

`test_score_points.py` 覆盖同曲 ID、难度隔离、默认版本优先级、缺失记录、分值更新及来源重建。
通过 `scripts/performance/command_checks.py --load-player` 运行时还验证已注册查分正则和处理器的结果；
所有执行继续使用既有 `memory/run_qa.sh`。

2026-11-16：安装版 0.25.2 的上述回归与 `tests/test_rating_targets.py` 共 39 项通过，
`pip check` 通过；公开曲库副本回放 `查分 合成器 377 221 117` 得到 805220。
旧版复现日志为 QA `qa-e86c0bcb7937`，安装版验证为 `qa-4e61ee4d3cb7`。
构建首次因 runtime-lock 仍指定 0.25.1 而未安装，更新锁文件后在候选环境完成安装；
随后通过 `TAIKO_DEPLOY_BOT_ONLY=1 scripts/deploy_taiko.sh 0.25.2 0` 发布 Bot。

## 0.25.3 同名曲全量复核

公开曲库包含 99 组同名曲、217 个 ID；按表/里谱检查 434 个 ID 与难度组合。
旧版默认 ID 缺失、而同组其他 ID 有分值的共 9 首、10 张谱面：
FAMIRES WARS、Fly away、我是合成器、Phoenix、浓红、Marionette Pure、
CYBERgenicALICE、不如就这样继续下去、Hater（含表里）。0.25.2 已恢复这些查询。
若包含指定其他版本 ID 的路径，同曲回退共恢复 91 个 ID 与难度组合。

复核另发现 0.25.2 将 ID 766「シンクロニシティ」的基础分值 2420 替换为
同译名 ID 523「Synchronicity」的 2240；二者音符数分别为 407 和 441，是不同歌曲。
0.25.3 优先读取该 ID 的现有记录，仅在记录缺失时使用同曲回退，保留修订缓存。
回归测试覆盖这两首歌和精确 ID 优先级。

43 组同名曲的表里谱均没有分值记录，属于既有数据覆盖范围，未生成猜测分值。
全量核对使用公开曲库副本，不连接数据库或发送平台消息，报告保存在
`/var/tmp/taiko-score-fix-20261116/duplicate-audit-0.25.2.json` 与相应 0.25.3 文件。

0.25.3 安装包在 QA `qa-200ff2998624` 中通过 40 项回归、`pip check`、真实曲库合成器回放，
源码与安装模块逐字节一致。全部 5978 个曲库 ID 与表里难度组合对照中，
旧版有效分值发生变化和新增失败均为零；受影响歌曲的 61 个别名与难度组合均通过。
随后使用 Bot-only 标准脚本发布 0.25.3。

## 本次结果

- 中心 300、客户端 260 条冻结事件对照；成功别名、可达/不可达 Rating、分值与估分数值通过。
- 双端数据集 26 个阶段，旧新写入次数和冷生成文件 SHA256 一致。
- 56 项中心授权/错误/统计场景，双端公开统计 8 项；无 IO 守卫违规。
- 6 种加载顺序、双端完整宿主加载；中心 12 / 客户端 11 个 player matcher。
- 既有命令代表性回归 194 项；单测 70 项及统计 subtest 192 项通过。
- 原 WIP 保留；无生产操作。未解决问题：无。
