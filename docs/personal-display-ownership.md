# 玩家个人展示与成绩筛选归属（0.8.0）

基线：Taiko `d396bda`，Sakura `db0ac3e`。三个命令均由
`taiko_bot.runtime.player.personal` 注册，中心与客户端不再注册旧入口。

- `my_don` 保留中心纯文本匹配和客户端 fullmatch 的区别。
- `song_metric_query` 保留原正则、单可/全良及 X 可/不可、排序、全连/全良排除、上下架与图片拼接。
- `tcloud` 保留三个别名、可选斜线、特定其他 Bot mention 排除、歌曲次数聚合、词云字体和 QQ Markdown 图片传输。

Host 复用 TinfoHostProvider / PreparedPrivateInput。中心的 Web 展示布局和称号覆盖
SELECT，以及自定义称号 SELECT、公开称号目录解析，全部在 Host 准备阶段完成。
连接或查询失败沿用原默认布局/自动称号回退。没有增加 DDL 或更改 SQL schema。
客户端由中心私有读取授权决定可读性。Renderer 只接收捕获的 current/profile/装扮和
已准备称号，使用现有记录计算接口，不持有 Provider、Writer 或数据库连接。
所有私人图片、错误和发送失败回退沿用 AuthorizedDelivery 的完整绑定复核。

Sakura 删除三个 matcher/handler、专用筛选实现、`utils/tcloud.py` 与
`utils/my_don_showcase_sync.py`。客户端也删除旧词云模块和无消费者的 mydon 包装函数。
中心 `draw_dress.py`、称号计算及目录模块仍供 `my_don_cli`、更新图和自定义称号功能使用；
两端更新图依赖的共享 dress/profile 绘图继续保留。新命令不反向导入这些 Sakura 模块。

测试在 `tests/personal`，隔离日志目录 `/var/tmp/taiko-display-20261015`。
只执行本次分支与已迁出命令的代表性回归，不重复完整存储/Core/Application 验收。

## 验收结果

2026-10-15：双端主矩阵各 52 个成功图片对照，中心称号/布局 72 个，
均比较 SHA256、尺寸和消息；双端筛选/错误用例各 146，安全用例各 144，
每端实际统计 114 条，无重复。隐藏、未绑定、发送前/发送失败撤权与成员/顺序/profile
变化均通过，渲染期间私人文件/SQL/网络访问 guard 无违规。
每端代表性回归：公开 18、tinfo 15、推荐 16、进度 16、B30 12、趋势 8；
相关单测中心 30、客户端 24，另有统计子断言 168。三种加载顺序和完整 Host 加载通过，
旧入口为零，九个公开及九个玩家 matcher 唯一。两端 pip check 通过。
冻结摘要与日志校验和在 `tests/personal/evidence`，完整隔离日志保留于上述目录。
没有未完成分支；未修改 Core/Contract、Writer/PublicationStore、SQL schema、Viewer 或 P0。
