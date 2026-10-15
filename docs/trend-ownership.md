# 历史趋势源码归属（0.7.0）

基线：Taiko `e0b3e08`、Sakura `7c98214`。

`taiko_bot.runtime.player.trend` 唯一注册 `taikotrend` / `rating走势` 和
`taikoplaytrend` / `rating场次` / `rating游玩`。中心默认 v2，支持显式 v1/v2；
客户端保留原 v1 参数集合，不接受 v2。TopN、窗口、维度、柱状图、显示全部、错误提示及图像使用原实现。

Host 复用 TinfoHostProvider 的绑定观察、native u0 物化、PublicationStore 读取租约和
客户端 current/history sourceView 配对。中心 `trend_history.capture` 在同一租约内捕获历史、
重建增量和准备测量；执行前核验完整绑定。`v1-topN` / `v2-topN` 使用已有
`b30_history` / `b30_daily` Storage 适配器：首次写入、当日较新快照更新、过去日期冻结、
源快照保留期结束后继续读取归档。没有更改 Writer、PublicationStore、锁、恢复或 SQL 协议。

中心 renderer 接收准备好的点集，客户端接收 PreparedPrivateInput 的捕获历史。
执行边界只接受值，不接受 Provider、存储句柄或写回 callback；输出沿用 Application
CommandResult 和 AuthorizedDelivery，发送失败回退也核验完整授权目标。

旧双端 matcher/handler、参数解析、趋势渲染和无消费者的历史计算已删除。
Sakura `score_calculator.py` 的记录计算与雷达/TopN 仍供 daily snapshot、回填、growth CLI
和更新图使用；`taikob_v2.py` 的计算仍供快照测量使用；`daily_ability.py`、
`draw_dress.py` 和 snapshot writer 保持原有实际消费者，不作为新趋势的反向依赖。

验收使用 `tests/trend/events.py` 的隔离事件、独立冻结源码及真实图片，详见
`tests/trend/README.md`。原趋势相关测试转移到 Taiko，Sakura 只保留快照 Writer 的测试。

## 本次验收

2026-10-15 隔离 fixture：冻结图片/消息对照中心 104、客户端 88；别名各 20；
历史场景中心 48、客户端 24；两个命令安全/统计中心 120、客户端 122；
命令级 v1/v2 archive 10；native u0 publication 5。全部通过。
代表性回归每端 public 18、tinfo 15、推荐 16、进度 16、B30 12；
中心相关单测 24 + 144 个子断言，客户端 23；两端三种加载顺序与完整旧 Host 加载通过。
日志保存在 `/var/tmp/taiko-trend-20261015`，未重复完整存储/Core/Application 验收。
