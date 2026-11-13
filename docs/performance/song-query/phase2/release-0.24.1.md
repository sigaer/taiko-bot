# 0.24.1 发布记录

用户在性能验收完成后明确授权“本轮完成，发布 0.24.1”。
2026-11-13 15:40:41（Asia/Shanghai）生产启动，15:41:26 完成核对。
代码提交 `4f755cfd2ac820196d837d5a815705a1d6a042bb` 已快进至 main。

- 生产 Bot **0.24.1** / Application **0.9.2** / Core **0.1.1**；其余依赖版本与 0.23.0 相同。
- 第一阶段不可变歌曲索引生效；固定 URL 开关保持关闭，默认使用现有随机 URL Markdown。
- 未激活安装包的 98 项中心端回归通过（90.81 秒），11 个改动模块与源码一致；`pip check` 通过。
- 生产 PID **3045312**，active、自动重启计数 0；原 37564 健康接口 HTTP 200，指定官方 QQ Bot 已连接，必要插件与实际进程版本清单通过。
- 真实公共曲库的隔离只读 `id649` 查询及 brief/同一快照检查通过；启动日志错误和 Markdown 缓存错误均为 0。
- 本次发布未新增 QQ 测试消息；不将 API 历史样本解释为生产端到端显示收益。客户端 profile、OneBot、QQ 客户端显示计时为 **OUT OF SCOPE**，未追加测试。

## 执行偏差

计划仅重启 Bot，但部署命令将 `TAIKO_DEPLOY_BOT_ONLY=1` 放在 QA wrapper 外层。
wrapper 清除了该变量，标准 `scripts/deploy_taiko.sh 0.24.1 0` 实际执行完整服务分支，
同时重启 `taiko-public-api`、`taiko-sync-receiver`、`taiko-song-update`（15:40:40）。
这与声明的 Bot-only 范围不符，不能记为仅重启 Bot。三者均已核对 active、自动重启计数 0。
Viewer 与内存监控未重启；没有手工替换程序输出或修改部署脚本。
源码工作区原有 `web.conf`、`v1_test_report.md` 的内容哈希未变，未纳入提交。

## 留存与恢复

新 Bot/Application wheel 已留存在 `/opt/taiko-bot/artifacts/`，校验值见机器可读证据。
原 `/opt/taiko-bot/releases/0.23.0` 环境保留。需要回滚 Bot 时使用现有标准脚本，并将环境变量放在 wrapper 内部：

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /usr/bin/env TAIKO_DEPLOY_BOT_ONLY=1 \
  /bin/bash /home/sigaer/taiko-bot/scripts/deploy_taiko.sh 0.23.0 0
```

本次未执行回滚；以上命令只切换 Bot，不表示回退已重启的其他服务。
第一阶段已记录的首次初始化/更新/模糊并发阻塞边界仍按原报告，不声称本次图片路径已修复这些风险。

构建 `qa-467b9988c110`，安装回归 `qa-38d017fc8a6d`，部署 `qa-273ee77922de`，生产核对 `qa-1033b54ffbe0`。
详见 [生产证据](release-0.24.1.json) 和 [安装包校验](release-0.24.1-candidate.json)。
