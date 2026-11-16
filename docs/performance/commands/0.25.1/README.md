# 0.25.1 更新与进度指令优化

2026-11-16。基线为已安装的 0.25.0，候选为已安装的 0.25.1；Core 0.1.1/0.1.2、Application 0.9.2、Contract 0.1.0 不变。

实时国服、Hiroba 和中心代理更新在原有 Source EX 与权限检查内捕获更新前的完整 current。更新图比较它与写入后的 current，不再重放歌曲/段位历史。写入后的 current 包含既有锁定成绩合并；首次数据信息明确传 None，不把历史当作本次更新的前态。历史持久化、权威写入及锁顺序不变。独立展示已保存更新图的旧 API 保留历史回退，实时更新明确绕过该分支。

进度的同步 prepare 使用独立的两线程输入池；每次调用在该线程创建并关闭自己的 SQL 连接和 Publication lease，只返回捕获的私有输入。绘图复用 B30 的两线程池，每池最多再等一个请求；传输及发送前权限复核仍在事件循环。普通进度逐行检查取消状态，字体按请求复用。普通进度和客户端段位 PNG 使用常规无损压缩，像素、尺寸、格式及排版不变，样本文件体积增长 1.82%～2.54%。中心段位仍使用现有 Application 编码，不声称本轮缩短了其计算时间。

原指令、分页、默认每类五项/全部、冷却静默、查询他人及隐藏规则、段位历史兜底、曲目上下架范围均保留。没有把“全部”改为查看上次结果，也没有自动刷新进度成绩。

## 离线实测

使用公开曲库/素材及 1520 条合成成绩，顺序运行在既有 QA cgroup 内。每例三次，保留首轮，表内为后两次的中位数。仅测计算和绘图，不含华立网络、SQL、排队与 QQ 上传。历史输入为合成的 JSON 字符串视图，不代表生产磁盘吞吐。

| 中心指令/样本 | 0.25.0 | 0.25.1 |
| --- | ---: | ---: |
| 10 星进度 | 3101 ms | 1766 ms |
| 10 星进度第 2 页 | 3016 ms | 1730 ms |
| 10.0 过关进度 | 668 ms | 300 ms |
| 9.0 综合进度 | 1319 ms | 571 ms |
| SS 进度 | 831 ms | 351 ms |
| 虹 2025 六段进度 | 1363 ms | 1333 ms |
| 更新图，100 份历史 | 948 ms | 384 ms |
| 全部更新图，100 份历史 | 883 ms | 389 ms |

客户端星级/过关/综合/自定义/段位样本降幅为 48%～57%。中心十例和客户端六例的 RGB 摘要、尺寸逐项一致。更新图 PNG 字节数亦相同；每次 100 份历史的更新绘图从 200 次历史解码降为零。

混合序列中的两份历史普通更新图样本为 406→451 ms，其中候选第二轮为 517 ms、第三轮为 384 ms；不将该短序列宣称为加速。另以七次独立更新回放复核：短历史普通图 406→391 ms、全部图 436→405 ms；长历史普通图 896→399 ms、全部图 898→434 ms。四例像素一致，保留在 update-check JSON 中，不与上述三次样本混算。中心进程峰值 RSS 为 328.9→313.9 MiB，客户端为 230.3→234.9 MiB；这是整个顺序基准的进程峰值，不是生产常驻内存或缓存归因。

## 回归与复现

已安装候选：中心 82 项、客户端 40 项、中心代理 11 项通过。覆盖原指令参数/冷却静默/首绑、国服与 Hiroba 更新前态、无前态/无变化/五项与全部、真实 Publication、输入线程内连接与 lease 生命周期、事件循环响应、撤权后禁止发送、私有读取缓存/304/版本一致性、曲目范围，以及执行器取消和容量回收。代码中十个变更运行模块与安装包 SHA256 一致，见 validation.json。

首轮验证遇到旧测试假包的相对导入、插件加载顺序和测试临时目录被生产路径 guard 拒绝；调整测试入口并保留 guard 后通过。另一个旧 merged-private 测试依赖已不存在的 test_private_renderer_reads，未计入通过数；本轮运行现存的私有缓存/一致性回归。没有重跑完整存储迁移或 Core/Contract 验收，没有生产 DB/成绩变更或平台消息发送。

所有命令均通过 `/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh`。基准入口：

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/releases/0.25.1/bin/python -I \
  /home/sigaer/taiko-bot/scripts/performance/command_latency.py \
  --fixture /var/tmp/taiko-command-performance-20261116/fixture \
  --output /var/tmp/taiko-command-performance-20261116/replay-center.json
```

客户端加 `--profile client`，使用原有 Core 0.1.2 overlay；更新专项加 `--updates-only --repetitions 7`。回归入口为 command_checks.py，使用 `--source` 指定已安装 site-packages，中心/客户端使用 `--fixture ... --load-player`，代理服务测试单独执行。原始 QA run ID 与输入文件摘要记录在 validation.json；完整日志留在私有 QA vault。

候选通过标准 build_release.sh 构建，`pip check` 通过。仅通过 `TAIKO_DEPLOY_BOT_ONLY=1 scripts/deploy_taiko.sh 0.25.1 0` 切换 Bot；Viewer 源码及服务、数据、素材不做发布修改。运行态只读证据写入 `/var/tmp/taiko-command-performance-20261116/before-production.json` 与 `after-production.json`，以其实际结果判断激活情况。
