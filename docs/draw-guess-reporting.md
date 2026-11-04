# 你画我猜举报去重（0.19.3）

原实现不记录举报人，同一个账号可以重复累加次数，连续举报五次即可停用作品。

中心和客户端现在共用 `runtime/community/reporting.py`。每条作品的
`reporter_ids` 保存平台限定的用户身份，同一用户跨群、重启或并发重复举报均只计一次。
`report_count` 从这份名单计算；达到五人时，在同一次数据库锁及保存操作中将
`active` 设为 `false`。重复举报和已停用作品返回明确提示，不写入记录。
图片仍保留，沿用原先的停用语义。

旧记录的匿名举报次数无法还原为不同用户。仍启用的旧作品在首次收到新举报时，
开始按新保存的举报人名单计数；此前的匿名次数不参与五人阈值。没有批量重写
记录，已停用的作品不会自动恢复。

回归入口（使用安装后的候选 wheel，禁止生产数据和网络访问；客户端需使用
安装 Core 0.1.2 的独立环境，将其 Python 路径设为 `CLIENT_PYTHON`）：

```sh
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/releases/0.19.3/bin/python -I \
  /home/sigaer/taiko-bot/tests/community/reporting_events.py center
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  "$CLIENT_PYTHON" -I \
  /home/sigaer/taiko-bot/tests/community/reporting_events.py client
```

验证真实适配器事件与处理器、跨群去重、重新加载、官方 QQ 身份、并发重复举报、
举报与点赞交错、第五人触发停用、旧记录、已停用记录及不存在 ID。
冻结旧处理器对照入口 `tests/community/events.py` 改为五个不同用户举报；
除显式断言并剔除新增名单字段外，继续比较原有消息与 JSON 字段。

2026-11-04：安装后的中心 wheel（Core 0.1.1）与独立客户端环境（Core 0.1.2）
均通过上述回归。中心 QA 证据为 `qa-6257a922b5db`，客户端为 `qa-43d6a99bf55e`，
保存在既有 QA vault 的 `runs/<ID>/evidence` 中。
