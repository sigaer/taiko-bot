# Viewer 段位进度历史读取修复

Viewer 安装适配层原先将段位历史转换为 B30 的 `capturedAt/payload` 输入；段位渲染器需要原始 `fileName`，在当前道场缺少所选段位且存在历史时抛出 `KeyError: fileName`。旧安装包可用合成 Publication current/history 复现该错误。

0.16.3 仅将段位适配层的历史输入改为从同一 Publication 只读视图获取 `fileName/payload`。渲染器原有文件名倒序选择、跨版本隔离、评分和图片布局不变；无效历史 JSON 继续排除，受管历史损坏仍拒绝，不回退投影。Core 0.1.1、Application 0.8.1 和 Contract 0.1.0 不变。

`tests/viewer/progress_history.py` 用已安装 wheel 运行 7 项回归，涵盖历史回退及原文件名顺序、当前道场、空成绩、缺失课题曲、损坏历史、渲染失败和锁释放；PNG 用原渲染器的正确输入结果做摘要对照。`--expect-baseline-bug` 在旧包复现故障，`--prepare-fixture` 为 Viewer 完整 HTTP 测试创建合成数据。测试禁止生产文件、SQL 及网络访问。

本修复供 Viewer 固定解释器使用；发布 Viewer 时指向已验证的 0.16.3 安装环境，无需切换 Bot 常驻服务。旧安装环境保留用于回滚。
