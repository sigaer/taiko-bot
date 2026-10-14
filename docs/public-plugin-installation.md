# Taiko runtime 安装与旧公共插件退役

当前候选：`taiko-bot==0.3.0`、Application **0.7.1**、Contract **0.1.0**。
九个公开入口与双端 tinfo 由 Taiko 内部模块维护；不再安装 `nonebot-plugin-taiko-song`。
本页替代旧 F-A/F-L 公共插件部署步骤。源码安装不表示授权部署或重启。

## 两个互斥 profile

中心和客户端必须使用不同的 Python 3.11 虚拟环境。中心选择 `[center]`（Core **0.1.1**），
客户端选择 `[client]`（Core **0.1.2**）。不得使用 `[center,client]`，也不得在同一环境轮流安装。
不要用历史测试锁、`--no-deps` 或强制覆盖掩盖依赖冲突。

从可读取的、固定提交的 Taiko checkout 根目录执行；配套 Sakura checkout 假设为同级 `Sakura_bot`：

```sh
# 中心专用环境
python -m pip install -r ../Sakura_bot/taiko/requirements-domain.txt ./packages/taiko-application '.[center]' -r ../Sakura_bot/taiko/requirements-application.txt 'nonebot-adapter-qq==1.7.2'
python -m pip check
```

```sh
# 另一个客户端专用环境
python -m pip install -r requirements-domain.txt ./packages/taiko-application '.[client]'
python -m pip check
```

使用新环境可避免已退役插件残留。若在未来经授权升级既有环境，先卸载旧插件，
确认 NoneBot 只加载 `taiko_bot.runtime.public`、`taiko_bot.runtime.player.entry` 各一次。
其余通用宿主插件、资源与配置沿用原宿主；不新建进程共享 QQ/OneBot 连接。

## 包获取与构建

Taiko 源码仓为 https://github.com/sigaer/taiko-bot 。候选分支 `feature/taiko-runtime-ownership`；
审阅时应 checkout PR 的完整 commit SHA，不能把可变分支当成发行锁。
Application 子目录和根项目在同一仓库中，以上一次 pip 调用同时提供两个本地候选，
因此不假设这两个版本已发布到 PyPI。Core/Contract 使用 requirements-domain.txt 内既有不可变 Git revision，
需要对应仓库权限；无权限时必须先取得同版本授权 wheel，不能替换领域版本。

若交付 wheel，从固定提交构建 `packages/taiko-application` 和根项目两个 wheel，记录 SHA256，
接收方使用显式 `--find-links` 与上述同一 profile 完整解析；构建的 `--no-deps` 不等于安装验证。
旧插件发行目录已删除；历史证据在 [测试归档](../tests/archive/public-song-plugin/README.md)，
当前有限验收在 `tests/runtime_ownership/`。

先审阅 Taiko PR、确认固定源码与依赖可取得，再审阅 Sakura PR。Sakura 删除的源码依赖已安装的
Taiko 运行包，不能先单独采用。保留生产 P0；不整目录覆盖生产，本轮不合并、部署或重启。
