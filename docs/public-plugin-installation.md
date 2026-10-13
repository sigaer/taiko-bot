# 公共插件源码安装与制品交付

适用：Application 0.5.0、nonebot-plugin-taiko-song 0.3.0、客户端 0.2.12。
九个入口为 what_song、alias_query、song_where、song_position_phrase、song_pos_by_id、diff_by_id、note_count、const_query、patterns。

使用 Python 3.11 和独立虚拟环境。Application 与歌曲插件直接从本仓两个子项目安装，不需要维护者的临时目录，也不假设这两个包在 PyPI 已发布。

## 客户端

在本仓根目录执行（先创建并激活虚拟环境）：

```sh
python -m pip install -r requirements-domain.txt
python -m pip install ./packages/taiko-application ./packages/nonebot-plugin-taiko-song -e .
python -m pip check
```

领域依赖通过 requirements-domain.txt 的精确 Git revision 获取，需要已有私有仓库读取权限；没有权限时由维护者提供 Core 0.1.2、Contract 0.1.0 wheel，先安装这两个本地 wheel，再执行第二、三行。禁止改用其他版本或跳过依赖解析。

## 中心源码宿主

中心只安装两个子项目，不安装客户端根包。中心 Core 必须为 0.1.1、Contract 为 0.1.0。
将锁定 revision 的 Taiko 与 Sakura 源码放在普通部署者选定的目录，例如互为同级的 `taiko-bot/` 与 `Sakura_bot/`；在 Taiko 仓根目录执行：

```sh
python -m pip install -r ../Sakura_bot/taiko/requirements-domain.txt
python -m pip install ./packages/taiko-application ./packages/nonebot-plugin-taiko-song -r ../Sakura_bot/taiko/requirements-application.txt
python -m pip check
```

这保留中心原有源码运行布局、其余宿主依赖与通用 feature_handler/runtime_memory/QQ 支持；不是把整个中心转换成 wheel，也不是完整服务器初始化说明。外部插件通过既有 NoneBot 插件列表加载一次，profile 为 center，公共资料根按宿主配置提供。客户端保留 client profile 和自己的公共资源获取。

## 本地 wheel 方式

制品维护者可在本仓根目录生成三个自有发行单元：

```sh
python -m pip wheel --no-deps ./packages/taiko-application ./packages/nonebot-plugin-taiko-song . --wheel-dir dist
```

此处 `--no-deps` 仅用于构建制品，不用于安装证明。将 wheel、SHA256 和所用源码 revision 一起交付到稳定制品目录；不提交运行数据或私有资源。接收者使用 `python -m pip install --find-links <制品目录> ...` 和相应精确版本/锁文件完整解析依赖。中心安装 Application 与插件，客户端再安装 taiko-bot；Core/Contract 未发布时也通过授权 wheel 或上述固定 Git revision 提供。

F-C 已验证的锁位于插件 `tests/catalog-acceptance/center-lock.txt` 与 `client-lock.txt`。使用这些锁时，自有三个包及 Core/Contract 必须先在显式制品源可用，不能假设 PyPI 存在它们。第三方依赖可来自正常索引；仅三个 wheel 不构成全离线镜像。

## 合并及上线边界

先审阅 Taiko PR 并确保依赖源码/制品可获取，再审阅配套 Sakura PR。新插件不得与仍注册原九入口的旧宿主同时活动。score_cmd 仍归原宿主，其自动刷新链未迁移。

源码合并不等于部署。Sakura 候选与生产 P0 的 Growth/score_calculator/daily_ability 存在差异，候选缺少生产 history_time_policy；未来发布须单独协调并保留 P0 修复，禁止整目录覆盖生产。此 PR 不带部署工作流、不执行重启，私有命令和基础设施不在本轮迁出范围。
