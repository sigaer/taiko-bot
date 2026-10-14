# 双端推荐命令所有权迁移（2026-10-14）

基线：Taiko `c11cdf7`，Sakura `6ca9b1f`。交付版本：taiko-bot 0.4.0、taiko-application 0.8.0。未部署、重启或读取生产 userdata。

## 实现

中心和客户端的普通、六维、目标推荐统一由现有 `taiko_bot.runtime.player` 插件注册，入口在 `player/recommendation.py`。中心保留 `歌曲推荐` 别名，客户端保留原别名集合；双端保留各自 Core、公开曲库来源、版式和错误消息。

沿用 `TinfoHostProvider`、`PreparedPrivateInput` 和 `AuthorizedDelivery`。Host 从已授权、已捕获的 current 计算并渲染，发送前重新检查授权与绑定；目标算法提取为显式记录输入，未重写 Core。客户端公开目录适配不再经过旧 `plugins.utils`。Application 复用原参数解析，并只用准备好的结果生成 CommandResult；新命令路径不会通过 user_id 再读成绩或调用 Writer。公开 scoreline 派生数据准备仍位于 Host 阶段。

兼容 API `RecommendationPorts` 仍保留给既有调用者，新 matcher 不使用其中按用户读取的回调。未更改 Writer、Contract、SQL schema、P0、Viewer、B30 或进度命令。

## 验收

只运行相关冻结参考、合成数据与有限回归。测试拒绝网络连接、生产路径读取，并检查计算/渲染期间不再打开私人成绩。所有真实 OneBot/QQ 分派都在隔离的 NoneBot 进程内运行，未连接线上机器人。

| 项目 | 中心 | 客户端 |
| --- | --- | --- |
| 冻结旧 handler/Core/图片对照 | 88 PASS | 84 PASS |
| 授权、撤权、隐藏、绑定变化、u0、错误及统计 | 52 PASS | 52 PASS |
| 统计入队 | 50 次，零重复 | 50 次，零重复 |
| 九个公开命令 × 两种协议 | 18 PASS | 18 PASS |
| tinfo 代表性安全回归 | 15 PASS | 15 PASS |
| 插件加载顺序 | 3 PASS | 3 PASS |
| 完整宿主加载 | PASS | PASS |

统计的另外两项为 OneBot 指向其他账号，沿用统计模块既有不计数规则。普通、维度、目标推荐的消息与图片 SHA256 均对照旧实现；唯一预期差异是旧中心普通/维度推荐将 u0 强转整数而失败，新路径恢复合法 u0 出图。旧 handler 的外层授权依赖由 fixture 注入；真实新 provider 的授权语义由独立安全测试覆盖。

静态审计确认旧入口均为零，中心其余 273 个、客户端其余 211 个顶层函数 AST 未变。实际加载确认每端只有一个 taikorec matcher。中心迁移相关六个单测（含两个渲染、别名/提示及 QQ 归属）通过，客户端目标推荐两个单测通过；统计三个测试、104 个子测试通过。安装 wheel 后双端依赖检查通过。

日志保留在 `/var/tmp/taiko-player-batch-20261014/`：`center.log`、`client-final.log`、`security-center.log`、`security-client-final.log`、`limited.log`、`host-center.log`、`host-client.log`、`targeted-center.log`、`finish-package.log`、`stats-unit.log`、`scope.json`。复现入口见 [推荐测试说明](../tests/recommendation/README.md)。

## 删除与保留

Sakura 删除旧 taikorec matcher/handler、推荐专用导入与常量、`plugins/utils/recommend_image.py`、旧 `generate_recommend_image`、旧目标图片 renderer/箭头 helper。客户端同步删除旧 matcher/handler、目标推荐与目标图片模块、普通推荐专属 helper。没有转发 adapter。

Sakura 的 `recommendation_intelligence.py` 仍为 Viewer CLI 消费者，因此保留其使用的共享 `target_recommend.py`、普通推荐计算和 scoreline/预测 helper。这不是机器人活动入口，新命令不反向导入它们；其后续归属不属于本轮。B30、进度及其 daily archive/history/measurement 依赖均未迁移。
