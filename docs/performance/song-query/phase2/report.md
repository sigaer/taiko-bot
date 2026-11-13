# 官方 QQ「是什么歌」第二阶段简化

2026-11-13，候选 Bot 0.24.1，基于 `b8ed34a`；未合并、未部署，功能默认关闭。
本轮仅官方 QQ 中心端；客户端 profile、OneBot、客户端显示计时均为 **OUT OF SCOPE**。

删除 Manifest、SHA-256 运行时校验、授权记录、有效期/续期、资源发布器、预热 hook 及对应工具和测试。
第一阶段索引、匹配语义、生命周期测试与独立基准原样保留。用户已确认所有谱面可公开。

新路径：查歌 → 校验 ID/难度、读取本地 PNG 头部尺寸 → Viewer 固定 URL → Markdown → 发送。
`TAIKO_QQ_FIXED_FUMEN_URL=1` 选择该路径，默认 `0` 沿用现有随机 URL Markdown；关闭即可回退。
固定 origin/路由，正整数 ID、五种难度白名单，无自定义 URL、远程查询、PNG 完整读取或随机缓存写入。
本地文件缺失/头部不可读或 Markdown 构造失败，在发送前回退；发送超时/结果未知直接抛出，禁止替换路径补发。
原有文字、模糊提示、难度及明确被动限制错误的主动发送规则不变。BXX、动态图片及 30 分钟缓存策略未改。

Viewer 现有接口：`https://viewer.sakura-bot.cn/api/content/songs/{id}/chart-image?difficulty={1..5}`。
其服务端校验歌曲/难度并流式返回 PNG（匿名 HTTPS，原有 Cache-Control 300 秒是 HTTP 缓存，不是资源租约）。
固定 URL 指向当前图片；本地预检不证明远端始终在线，也不完整校验 PNG 正文。
远端在发送后失效不能安全补发；部署前验证接口与 QQ 域名可用，故障时关闭开关。无需新运维任务或资源副本。

## 实际 QQ API 对比

同一真实谱面 Oni/649、同一既有私有测试 Bot/群；6 个新被动事件，依次原生、随机、固定、固定、随机、原生。
每种 n=2，仅探索性原始样本和中位数，不推断 P95/P99 或生产 SLA。
原生计入 `post_group_files(srv_send_msg=False)` 上传及 `post_group_messages` 两次 API；两种 Markdown 各一次消息 API。
token 在样本前预热；沿用已安装 QQ 参数构造器及 HTTP driver，每个请求独立连接。准备、Viewer GET 校验不计入 QQ API 时间。

全部 6 次消息 API、2 次仅上传 API 为 HTTP 200 / acknowledged，每个事件只尝试一条消息，无重试。
用户已回复“已发送”；不将 API 确认表述为客户端显示计时或当前图片接收观测。
同图匿名 HTTPS GET 返回 200、image/png、85,957 bytes、816×1648，与本地一致；SHA 仅用于本次样本等同性检查，不进入运行时路径。

| 方式（各 n=2） | QQ API 原始样本 ms | 中位数 ms | 本地准备 ms（原始样本） |
|---|---|---:|---|
| 原生图片上传 + 消息 | 2649.030、2279.949 | 2464.490 | 0.063、0.105 |
| 当前随机 URL Markdown | 1603.368、1874.599 | 1738.984 | 0.938、0.741 |
| Viewer 固定 URL Markdown（首次、重复） | 3195.988、1661.948 | 2428.968 | 0.295、0.326 |

n=2 中位数取两个值平均。原生两次上传分别 564.078 / 562.299 ms，随后消息分别 2084.952 / 1717.650 ms。
固定 URL 首次较慢、重复样本较快，不能据此认定 QQ 缓存命中或稳定收益；HTTP trace 中主要时间在等待响应头，未测 QQ 内部抓图阶段。
**选择：默认保持当前随机 URL Markdown。** 固定 URL 在本次样本没有稳定 API 速度优势；本地准备差别约 0.53 ms，不构建任何额外资源设施。
保留 30 行固定 URL helper 和一个关闭的开关，作为复用既有接口的轻量选项；不推荐以“已提速”为由启用。
该选项移除完整图片读取/随机复制，但本轮不声称实际端到端提速。
原始 API/HTTP trace、依赖和预检见 [qq-api-comparison.json](qq-api-comparison.json)，隔离 QA `qa-cc9b4fea22f4`；无凭据或目标标识。
JSON 的 package metadata 属于已安装 0.23.0 环境；helper/公共消息构造器加载本工作树，Application 加载仓库 0.9.2 源码，QQ SDK/HTTP driver 使用已安装版本。

## 回归与保留证据

本轮 **98 passed / 21 deselected，92.78 秒**：中心端原有 69 项及新增 29 项。
包含真实曲库 2,989 首/2,071 条别名、16,111 个唯一字面量差分，以及匹配阶段、更新、损坏恢复、并发快照、五难度、模糊文案、回退及超时后单次发送。
未执行客户端/OneBot 用例；测试内固定 URL 命中不完整读取 PNG、不解码像素、不写随机缓存，但会读取 PNG 头部，不能宣称零 PNG I/O。
环境：Linux 5.10、Python 3.11.4、nonebot2 2.5.0、QQ adapter 1.7.3、httpx 0.28.1、Pillow 11.3.0、Core 0.1.1。
QA 串行隔离于 2 CPU/3 GiB 上限；回归 CPU 93.214 秒，进程 max RSS 158.73 MiB，OOM=0。
详见 [validation.json](validation.json) 与 [test-resources.json](test-resources.json)。

旧三次 QQ 真发送及用户确认、200 项回归、Manifest 命中零 PNG/随机文件证据封存于 [history](history/README.md)，保留为历史 PASS。
不将不同阶段或不同管线 P50 相减作为端到端收益；原索引阻塞风险没有在本次图片路径简化中修复或重新测试。

本轮 Gate：代码回归 **PASS**；同图三路官方 QQ API 对比 **PASS**；固定 URL 稳定提速 **未证实**。
不启用生产开关、不合并、不部署。实际发送已结束，隔离进程退出；原生产 PID 2886113、11:24:19 CST 启动时间不变。
