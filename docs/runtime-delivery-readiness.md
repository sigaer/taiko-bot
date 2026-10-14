# Phase 2F-E 合并前交付整备

状态：**PRE_MERGE_DELIVERY_CHECKS_PASS**。沿用两仓 `feature/taiko-runtime-ownership`，
本轮仅处理安装入口、退役目录、文档与有限验收；没有重新抽取功能。

- Taiko 0.3.0 精确依赖 Application 0.7.1；Sakura requirements 与 pyproject
  均选择同一个 `[center]`。旧插件不能作为第二安装入口。
- 历史插件发行目录已移除；24 个测试、fixture、锁及验收文件逐字节迁入
  `tests/archive/public-song-plugin/`。保留历史 Git 路径用于冻结源码审计；
  当前验收使用 `tests/runtime_ownership/`。旧锁仅作历史证据。
- 中心与客户端在两个全新 Python 3.11 环境中完整解析、安装，未使用 `--no-deps`
  绕过安装解析。中心 Core 0.1.1 / QQ 1.7.2；客户端 Core 0.1.2 / QQ 1.7.3；
  双端 Contract 0.1.0，`pip check` 均通过。同选 `[center,client]` 的 dry-run
  因 Core 精确版本冲突返回 `ResolutionImpossible`。
- 有限检查：双端各 18 个公开命令真实事件（九入口 × OneBot/QQ）、各 15 个
  tinfo guard-smoke（旧处理器文字/图片/错误比较、四个撤权点、三个陈旧目标检查），
  六种插件装载顺序均通过。每个进程九个公开 matcher、一个 tinfo matcher。
- 本轮业务源码、Application、Provider、Writer、存储与锁实现对交付基线字节不变。
  保留既有完整业务/存储验收证据，不重复完整矩阵。重新构建 wheel，并确认其中的
  Python 源码、安装后的源码与候选工作树一致。

完整版本与逐项结果见 [验收 JSON](runtime-delivery-validation.json)；当前安装步骤见
[运行包安装](public-plugin-installation.md)。临时构建/解析日志位于
`/var/tmp/taiko-phase2fe-20261014/evidence/`。旧临时工作树与环境在本轮开始时缺失，
已从原分支恢复；没有更改原 main 工作区 WIP。

检查全部经既有 `scripts/memory/run_qa.sh` 执行。tinfo 仍使用原验收脚本的真实
renderer 和冻结处理器；公共封面 359 在合成 fixture 中用作 278 的输入，旧新两路一致，
不与上一轮资源下的图片 hash 混比。公开入口新增检查是响应冒烟，历史完整 parity
记录继续保留；没有将它冒充新的完整矩阵或真实联网 Bot 会话。

审阅顺序：先 Taiko（运行包、两种 profile、源码/制品可取得），再 Sakura（依赖声明、
装载配置与对应源码删除）。私有领域包需既有仓库权限或授权 wheel；不宣称发布到 PyPI。
两仓 PR 都面向 main。本轮不合并、不部署、不重启，不修改 Viewer、SQL、生产数据或 P0。
