# 双端进度命令迁移（2026-10-14）

基线 Taiko `66b60ee`、Sakura `f49b205`。交付 taiko-bot 0.5.0，复用 Application 0.8.0，Core/Contract 不变。

进度 matcher/handler 位于既有 `taiko_bot.runtime.player.progress`。中心保持 on_message 和原纯文本提取规则，客户端保持原正则；两个宿主均排除其他 bot 的任务、账单、PJSK 和活动进度。客户端新增该排除规则，避免未绑定错误误响应其他 bot 指令。星级、定数/综合、过关、段位、自定义和分页统一调用现有 Application Progress 用例；两端保留各自旧渲染与曲库/上下架筛选。

TinfoHostProvider 扩展可选历史准备，默认 tinfo/推荐路径仍不取历史。中心在既有共享 lease 内取得 current/history；当前 dojo 已有成绩时不扫描历史，缺失时按原顺序仅捕获最新匹配 dojo，避免积累无关歌曲历史。客户端按已有 sourceView 规则匹配同一版本、最多两次尝试。未更改 PublicationStore、Writer、锁或恢复协议。

渲染只接收 PreparedPrivateInput 解冻出的当前成绩、历史数据和装扮 profile。段位沿用原文件名倒序、dojo 查找、版本及时间规则：中心仅 2025 dojo 数据回退，客户端仅其当前 2025 版本回退；当前 dojo 成绩优先。不在 renderer/Application 扫描私人文件，不通过 user_id 再读成绩。发送及 QQ 失败回退沿用 AuthorizedDelivery。

Sakura 删除旧 matcher/handler、专属参数解析、四类普通进度 renderer、失去消费者的表格/星级 helper 和 progress_star.py。旧 dani_progress.py 删除私人读取、历史兜底和段位进度 renderer；保留段位总览使用的公开配置及绘图 helper。progress_catalog.py 仅保留更新变化图仍使用的上下架目录 helper；其进度查询实现已迁出。客户端同步删除旧入口、专用段位模块及星级模块。共享装扮与更新图函数仍有消费者，未误删。无转发 adapter。

Sakura 统计注册到新 progress matcher，保留其他账号 mention 的不计数规则。两端每种加载顺序只有一个进度入口。

验收使用冻结旧源码与合成数据，命令见 [测试说明](../tests/progress/README.md)。必要日志保留于 `/var/tmp/taiko-progress-20261014/`，最终结果见该目录 `report.md`。未重复完整存储、Core、Contract 或 Application 验收。

未部署、重启、访问生产私人数据，未修改 Viewer、SQL schema、生产 P0。B30 未迁移。

## 验收结果

| 项目 | 中心 | 客户端 |
| --- | --- | --- |
| 双协议、普通/u0、各分类/分页、装扮及历史图片对照 | 92 PASS | 92 PASS |
| 最终历史准备收紧后的追加对照 | 24 PASS | 不涉及 |
| 授权/隐藏/未绑定/撤权/绑定变化/保留命令/统计 | 56 PASS | 57 PASS |
| 应记录调用，零漏计/重复 | 46 | 47 |
| 九个公开命令 × 两协议 | 18 PASS | 18 PASS |
| tinfo 代表性回归 | 15 PASS | 15 PASS |
| taikorec 普通/维度/目标代表性回归 | 16 PASS | 16 PASS |
| 加载顺序 | 3 PASS | 3 PASS |
| 完整宿主加载及唯一所有权 | PASS | PASS |
| 相关单测 | 4 PASS，含 120 个统计子测试 | 3 PASS |

统计不计数的十项分别为两项其他账号 mention、八项其他 Bot 的保留指令。客户端额外一项验证 current/history 版本不一致时拒绝输出。最终历史测试确认中心每次最多捕获一个 dojo 历史项，current 已有 dojo 时不读历史。

安装 wheel 后双端 pip check 通过。最终补验耗时 210.13 秒，子进程峰值 RSS 218384 KiB，在受限 QA cgroup 中串行完成。公开/已有用例只跑代表性回归，未重跑完整存储协议验收。

日志：`final-parity-center.log`、`final-parity-client.log`、`history-center.log`、`security-center.log`、`security-client.log`、`limited.log`、`units-center.log`、`units-client.log`、`final-verify.log` 和 `scope.json`，均位于上述隔离目录。
