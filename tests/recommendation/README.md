# 推荐命令离线验收

`events.py` 在隔离进程中生成公开曲库/合成 userdata，加载真实 player matcher，通过 OneBot/QQ 事件分派。中心 SQL 行为由只读 fixture 提供，PublicationStore/u0 使用临时目录；客户端远程接口用 fixture 响应。禁止连接网络及打开生产路径。

准备两个干净基线目录：Sakura `6ca9b1f` 的 `taiko/plugins`、Taiko `c11cdf7` 的 `plugins`（用 `git archive` 导出）。`freeze.py` 仅提取旧推荐 handler 的依赖闭包；`frozen_application.py.txt` 是基线 Application 用例。assets 必须是隔离复制的公开字体和图片，不能指向生产目录。

在装有候选 wheel、对应中心/客户端 Core 和宿主依赖的独立虚拟环境运行（以下路径均用绝对路径替换）：

```sh
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh /absolute/venv/bin/python /absolute/taiko/tests/recommendation/events.py --host center --baseline /absolute/baseline-center/taiko --work /var/tmp/rec-center --assets /absolute/public-assets --application /absolute/taiko
```

客户端使用 `--host client` 和客户端基线目录。加 `--mode security` 验证现有 provider、发送前撤权、隐藏/绑定变化、捕获数据、错误和统计；统计 fixture 使用同级 `sakura/taiko` 源码（见 security.py）。两类测试分别使用新的 work 目录，串行运行。输出 `events.json`/安全结果及控制台 PASS，图片仅比较摘要，避免二进制日志。

`scope.py <taiko-worktree> <sakura-worktree>` 检查旧入口和非目标函数 AST、禁止范围及反向私有依赖。`tests/runtime_ownership` 的 load_order、delivery_smoke 和 events `--guard-smoke` 分别覆盖加载顺序、九个公开命令和 tinfo 代表性回归；public_dispatch `--load-only` 验证完整旧宿主与新插件共存时的唯一所有权。

本轮未重跑完整 Application、存储协议或公共命令矩阵。
