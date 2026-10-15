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

## 本次结果

- 中心 300、客户端 260 条冻结事件对照；成功别名、可达/不可达 Rating、分值与估分数值通过。
- 双端数据集 26 个阶段，旧新写入次数和冷生成文件 SHA256 一致。
- 56 项中心授权/错误/统计场景，双端公开统计 8 项；无 IO 守卫违规。
- 6 种加载顺序、双端完整宿主加载；中心 12 / 客户端 11 个 player matcher。
- 既有命令代表性回归 194 项；单测 70 项及统计 subtest 192 项通过。
- 原 WIP 保留；无生产操作。未解决问题：无。
