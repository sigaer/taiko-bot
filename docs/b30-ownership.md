# 双端 B30 源码归属（2026-10-14）

基线 Taiko `7426c2b`、Sakura `73adfc2`；交付 taiko-bot 0.6.0，Application 0.8.0 不变。

既有 `runtime.player.b30` 独占 taikob matcher/handler，复用 Application B30、Core、TinfoHostProvider、PreparedPrivateInput 和 AuthorizedDelivery。中心保留默认 N=20/v2 与 on_message，客户端保留必须指定 N、默认 v1 与原 on_regex。汇总、TopN、维度、雷达、版本和参数错误使用迁入的两端实现。客户端表格去除不必要的整数 ID 强转，使原先报错的 native u0 正常出图。

中心 current、ctime、history 在同一 publication lease 内捕获，沿用 native u0 物化和依赖校验。客户端汇总图通过既有 sourceView 配对，变化最多重试两次。榜单/维度分支不取私人历史。装扮使用捕获的 profile；计算和渲染不得按 ID 再读私人数据。中心公开 v2 模型也在 Host 捕获，渲染不触发网络刷新。Application 只获得捕获数据绑定的计算/渲染函数，不获得 provider、Writer、store 或写回回调。

历史测量、store_measurement 及 archive 适配均留在 Host，调用既有 PublicationStore/daily_archive。冻结旧实现有一个必须保留的区别：B30 汇总图显式传入聚合函数，因而 `custom=True`、namespace=None，测量临时日表；命名历史趋势使用持久化 archive。没有把有名 archive 改成禁写，也没有给 B30 凭空新增命名空间。独立对照验证命名 archive 的首次写入、热请求、今天新快照、过去日期不可变及源快照保留期后的读取。

双端旧 taikob matcher/handler、专用解析、维度表、v2 命令渲染函数和 `plugins/utils/b30_render.py`、`b30_single.py` 已删除，无转发模块。共享 score_calculator/taikob_v2 的计算、趋势和测量代码仍被 draw_summary、历史趋势、更新及快照路径使用，保留。客户端已无其他消费者的旧 `plugins/utils/taikob_v2.py` 一并删除，相关测试指向新所有者或 Core。共享装扮和历史工具亦保留。Sakura 统计注册到新的唯一 matcher，其他账号 mention 仍不计数。

[隔离验收说明](../tests/b30/README.md)。必要日志与结果 JSON 位于 `/var/tmp/taiko-b30-20261014/`，最终汇总为该目录 `report.md`。未部署、重启或读取生产私人数据；未修改 Writer/PublicationStore 协议、SQL schema、Viewer、Core/Contract 或生产 P0。

客户端原先未捕获的 current 获取失败，现在通过已授权的 Host 错误通道返回原错误文字；不回退旧缓存。发送失败验收还修复了 AuthorizedDelivery.finish 的失败后复核，正常 FinishedException 结束语义保持不变。

## 验收结果

| 项目 | 中心 | 客户端 |
| --- | --- | --- |
| 双协议普通/u0 基本成功图像与错误对照 | 36 PASS | 32 PASS |
| N、版本、包装/flag 参数边界 | 36 PASS | 32 PASS |
| 首次/热/变化/缺失历史图像 | 32 PASS | 16 PASS |
| 无成绩、低良率、current/公开模型缺失 | 18 PASS | 16 PASS |
| 隐藏/未绑定/撤权/绑定变化/发送失败/统计 | 60 PASS | 61 PASS |
| 上述应记录调用，无漏计/重复 | 50 | 51 |
| native u0 首次/热/成员/profile/current publication | 5 PASS | 中心授权配对检查覆盖 |
| 命名 archive 数据及耐久写入次数 | 5 PASS | 不写 archive |
| 最终 wheel 实际 B30 图像抽检 | 12 PASS | 12 PASS |
| 公开/tinfo/推荐/进度代表性回归 | 18/15/16/16 PASS | 18/15/16/16 PASS |
| 相关单元测试 | 13 PASS + 128 统计 subtests | 7 PASS |

两端各三种装载顺序均为公开 matcher 9、玩家 matcher 4；完整宿主装载验证旧 taikob 为零。最终 wheel 对应维护源码，不含已删除的客户端旧模块。存储协议完整验收沿用既有证据，仅补本次 Host 历史/测量路径的对照。
