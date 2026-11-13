本目录封存 `b8ed34afdafd3116a390ae59fdf85430c284d9bf` 的原始第二阶段证据。
原报告针对已删除的 Manifest 实现，不是当前实现的性能或发布 Gate。

保留结论：200 项历史回归通过；原静态命中零 PNG 读取、零随机文件写入；
官方 QQ 三次真实发送成功，用户确认各收到一次、正常显示。
这些结果不能替代本轮 Viewer 固定 URL 的实测。

原报告中的客户端 profile、OneBot 与客户端显示计时现为 **OUT OF SCOPE**，
其历史 PENDING 不再构成发布阻塞。当前结论见上级 `report.md`。
`artifacts.json` 对应原提交中的路径/内容，不用于校验移动后的历史目录或当前实现。
