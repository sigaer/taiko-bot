# 双端进度命令离线验收

使用基线 Taiko `66b60ee` 的 `plugins/` 和 Sakura `f49b205` 的 `taiko/plugins/`（git archive 导出），以及隔离的公开素材目录。候选 wheel 安装在独立中心/客户端环境，分别保持 Core 0.1.1 / 0.1.2、Contract 0.1.0、Application 0.8.0。

通过内存隔离 wrapper 串行执行：

```sh
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh /absolute/venv/bin/python /absolute/taiko/tests/progress/events.py --host center --baseline /absolute/baseline-center/taiko --work /var/tmp/progress-center --assets /absolute/public-assets --application /absolute/taiko
```

客户端用 `--host client` 与客户端基线。每次使用空 work 目录。生成 65 张合成图谱、合成 current/history 与可见装扮图层；公开段位向量来自已冻结 Application fixture。原素材通过目录符号链接使用，合成装扮只写测试目录。无需复制生产私人数据。

普通验收对照冻结旧 handler、渲染器、图片 SHA256 与错误/静默行为；覆盖双协议、普通/u0、星级/定数/综合/过关/自定义、真实跨页和越界页、段位当前成绩/历史兜底及版本边界。旧 handler 的外层绑定解析由 fixture 注入，新 provider 的授权行为单独测试。

添加 `--mode security` 覆盖真实 provider、撤权/隐藏/未绑定/绑定变化、统计入队及其他 bot 的保留命令，客户端另验证 current/history 版本不一致时两次重试后拒绝。中心使用原 PublicationStore 的隔离目录和只读 SQL 行 fixture；客户端使用原 private reader 与模拟 HTTP 响应。禁止真实连接、生产文件打开，以及计算/渲染阶段再次读取私人文件或导入旧 plugins。

`scope.py <taiko-root> <sakura-root>` 检查旧入口为零、其他函数 AST 不变、禁止范围未修改和 renderer 无私人读取依赖。`tests/runtime_ownership` 提供加载顺序、完整宿主 `--load-only`、九个公开命令和 tinfo `--guard-smoke`；`tests/recommendation/events.py --representative` 提供普通、维度、目标推荐的代表性回归。
