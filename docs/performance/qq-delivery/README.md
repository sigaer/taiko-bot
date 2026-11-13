# QQ 官方图片发送独立实验

工具入口：[qq_delivery_probe.py](../../../scripts/performance/qq_delivery_probe.py)。
基线为 Bot 0.22.1 / Application 0.9.1；工具不在打包的业务模块或 Bot 启动插件列表中，
不会改变 `taikob`、默认回退、玩家成绩、权限、绑定、绘图或监听端口。
报告文件为 `qq-delivery-results.json`、`qq-delivery-comparison.md`、`qq-delivery-errors.json`。
它们只包含合成图摘要、随机实验编号和脱敏数值，不包含群/管理员 openid、消息 ID、
`file_info`、鉴权头、密钥或完整测试 URL。私有配置、状态和媒体凭据禁止入库。

## 运行环境与鉴权

始终使用 `/opt/taiko-bot/current/bin/python -I` 和既有内存隔离包装器。
工具仅将自身的 `scripts/performance` 加入路径，QQ Adapter、HTTPX、Pillow 和
应用包均来自当前安装环境，不从源目录冒充生产版本。`inventory` 记录实际版本和 API 签名。

工具的 `Transport` 可接受现成的 Bot 对象，在同一进程复用其鉴权获取器；
不修改该对象、Adapter、全局 API hooks 或生产连接池。
当前生产进程没有提供跨进程取出该 Python 对象的接口。CLI 明确使用隔离 worker，
读取既有运行配置选择同一个 Bot，使用独立的鉴权缓存；没有复制 Token 或 AppSecret 到脚本/状态。
`listen` 在同一 worker 中连续处理新的管理员事件，可复用该 worker 的鉴权缓存。
原生产 Bot 保持在线提供真实 QQ 事件；worker 不启动 WebSocket、HTTP 服务或业务插件。
报告将这种鉴权来源标为 `isolated_bot_existing_config`，不能冒称生产已建立的鉴权对象。

`adapter` 路径调用安装版 Adapter/driver 的 HTTP 请求。
`traced_httpx` 使用同一安装驱动的 session 工厂、版本、代理和超时，
仅在实验自己的会话上增加 HTTPcore trace；两条路径分组统计。
已核实安装的 NoneBot HTTPX driver 每请求新建 session/client，因此不能将连续请求
称作复用了 HTTP 热连接；鉴权缓存热命中与 HTTP 连接复用分别记录。

两条路径都用安装版 `Bot.post_group_files` / `post_group_messages` 构造实际参数。
实验专属的请求处理关闭401自动重发，不记录原始响应或异常文本；生产 SDK 的行为不变。
安装版 `PostGroupFilesReturn` 不声明消息 `id`，工具只从原始响应提取其存在性，
不会将其缺失误判为平台从未发送。

## 默认 dry-run 与私有配置

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/current/bin/python -I \
  /home/sigaer/taiko-bot/scripts/performance/qq_delivery_probe.py inventory
```

不带子命令、`inventory`、以及未带 `--live` 的 `run`/`listen` 均为 dry-run，
不加载 Bot 密钥、不取 Token、不请求 QQ API，也不公开图片。
配置模板见 [private-config.example.json](private-config.example.json)。
真实发送必须同时具备 Bot、测试群、主动测试许可、单轮上限，另需指定授权管理员。
配置文件0600、状态目录0700；拒绝符号链接配置、串换目标和未知字段。
`max_sends_per_round` 必须1～6，默认建议3；间隔至少20秒，当前实验采用25秒。

用户明确指定某条“开始测试”所属群后，可私下从原生 QQ 日志绑定唯一目标：

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/current/bin/python -I \
  /home/sigaer/taiko-bot/scripts/performance/qq_delivery_probe.py \
  bind-start-event --private-dir /var/tmp/taiko-qq-delivery-private \
  --authorize-active --max-sends 3
```

只接受 `nonebot` 日志命名空间下的原生 QQ 群事件描述，并用安装版 Message 的表示匹配
完整触发文字，不接受消息正文里伪造的日志。最近一小时有多个不同 Bot/群/作者匹配时拒绝绑定。
该日志桥接只支持受信本机 journald，不能当成远端 webhook 校验接口。
工具不会输出选中的身份字段。无用户指示时不能靠此命令自行挑选测试群。

## 协议预检与单次发送

先核实管理后台的主动权限、群主动开关和额度；已知权限为 false 时禁止 B。
未知能力只能进行一次受授权的主动协议试验，不从旧文档推断接受与否。
第一条 B-data 预检可使用“开始测试”作为操作授权事件，**不会把其 ID 放进 B API**：

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/current/bin/python -I \
  /home/sigaer/taiko-bot/scripts/performance/qq_delivery_probe.py \
  --config /var/tmp/taiko-qq-delivery-private/config.json \
  --output /var/tmp/taiko-qq-delivery-live-report \
  run --mode B-data --live --start-trigger
```

也可在私有目标已明确绑定、主动测试许可和单轮预算有效时，显式执行
`run --mode B-url --live --active-trial`。该入口只允许协议阶段每条 B 路径一次，
不需要用户消息，不伪造或传入被动 `msg_id`；重启、换轮号也不能再次使用已预留的路径。
这只执行当前明确指定的一次试验，不循环发送。

其余真实发送由指定管理员在指定群发新的 `/qqprobe 模式` 触发；
支持 `A-data`、`A-url`、`B-data`、`B-url`、`C`、`D`。
对应执行 `run --mode A-data --live --wait-seconds 60` 等命令。
A/C/D 的事件必须在120秒内，固定回复序号1，每个事件仅使用一次，跨轮/重启也不能重用。
模式、Bot、群和管理员都必须匹配私有配置，真实消息不是脚本伪造的 `msg_id`。

- A-data / A-url：上传 `srv_send_msg=false`，然后只发送一次富媒体被动回复。
- B-data / B-url：仅一次上传 `srv_send_msg=true`，不附加文字、不再发送第二条消息、没有被动 ID。
- C：合成图通过 HTTPS 完整字节与 Content-Type 校验后，发送原始 Markdown 被动回复，包含测试文字。
- D：仅发送一次已有媒体凭据，不上传；凭据来自成功的 A，同 Bot/群/合成图限定，不跨目标。

失败记录数值错误码、HTTP状态和固定类别；不保存错误正文、trace ID 或 URL。
B 的平台拒绝会停止两个 B 路径，需要人工定位，不自动尝试另一条路径。
超时、取消或进程崩溃留下未知结果，会阻止所有后续真实发送；先人工检查群消息，
再用 `observe` 记录结果，不重发该事件、不自动退回 A。
只有 `file_data` 错误被确认是输入能力不支持、而不是权限/额度问题时，才可由维护者
在私有状态中人工解除 B-url 停止标记并用一个新事件单独试验；工具没有自动解锁或重试入口。

状态使用跨进程非阻塞文件锁、原子替换、文件和目录 fsync，在网络调用前持久化
预算与事件消耗。未完成预留恢复后视为未知，预算不退还；修改轮号也不会消除未知结果。
每模式协议阶段最多3条；性能阶段每模式默认10条，扩展至20需额外许可。
B 的性能阶段还需要独立主动性能许可及已观察到的剩余额度。
新增轮号只重置该轮预算，保留上轮间隔、事件消耗、失败和未知记录。

D 要求明确非负 TTL；缺失 TTL 不缓存。平台 TTL=0 按文档表示长期，
实验仍自行限制30分钟租期，其他 TTL 也最多保留30分钟。有效期从上传请求开始计算，
发送前留5秒余量。过期直接拒绝，无自动重传；发送时媒体被平台拒绝会清空私有凭据并停止 D。

## 交错测试与暂停继续

不提供自动批量发图。`listen --modes A-data B-data C D --seconds 300 --live`
仅在指定管理员主动发出对应的新命令时处理一条，单线程共享鉴权对象。
轮预算耗尽、暂停、模式错误或未知结果时停止；重复轮询同一个事件不会重复发送。
等待事件不是重试 QQ API。`--seconds` 最长1800秒，实际仍受单轮最多6条限制。
建议每轮采用 A→B→C、B→C→A、C→A→B，D 在有效 A 凭据产生后插入；
每条间隔25～30秒以上，遇到平台实际频控立即停止，不提高速率追样本数。

`pause` / `resume` 只修改私有实验状态，不改变群设置。
可用 Ctrl-C 安全中断；被取消的请求结果仍需人工核对。
原进程持有锁时，第二个 CLI 不会等待或抢占；需要先中断监听器，再编辑状态/录入观察。

## 公网合成图隔离与清理

图片由工具直接生成，固定1080×2436 JPEG、约500～800 KiB，无 EXIF、玩家信息或用户标记。
没有传入任意图片文件的参数。同一图片复用，避免靠大量重复造图提高样本数。
公开目录必须独立命名为 `qq-delivery-probe`，带专用 marker，只写 `probe-随机文件名.jpg`。
工具在隔离模块实例中复用安装版 `qq_markdown_media.py` 的缓存函数，
不修改生产模块全局配置，不使用真实 BXX 或生产私人图缓存。

公开前须有独立自动清理 timer；模板在 [cleanup](cleanup/) 中。
模板只删除该 marker 目录内过期的 `probe-*.jpg`，默认5分钟后删除，
每分钟尝试一次，使用现有串行 QA 包装器；遇到 QA 锁占用会延后至后续轮次。
维护者安装并启用该独立 timer 后才允许发布测试图，不重启 Bot、Viewer 或 Web 服务。
实验结束须删除残余合成图、验证源站404并关闭不再需要的 timer。

静态 URL 使用已配置 HTTPS 前缀，文件名由现有缓存函数随机生成，完整 URL 仅在私有状态和
发送至授权测试群的 Markdown 中出现。配置 `external_probe_proxy` 时，
仅静态 GET 使用该独立外网代理验证 TLS、200、`image/jpeg` 和整张 JPEG 的字节一致性，
QQ API 的网络策略保持原配置。若无代理，需要管理员确认外网访问，并另做本机完整校验。
`domain_preflight_authorized=true` 只允许协议阶段试验未知白名单，不等于白名单已确认；
性能阶段需要 `domain_whitelisted=true` 的确认。

验证 GET 自身可能预热 CDN，所以 `first_url` 仅指缓存函数首次生成的 URL，
`repeated_url` 仅指缓存函数复用了 URL，失败预检或单独 HTTPS 校验也可能已经生成过该 URL；
不能当作完全冷 CDN；客户端是否缓存须单独在观察中记录。
既有公网缓存头可能允许缓存约30分钟，删除源站文件不保证 CDN/客户端立即抹除。
因此该方案目前仅适用于本次公开合成图；没有证明能满足真实私人 BXX 的隐私要求。

## 客户端观察与时间口径

用 Android QQ，尽可能同时用 Windows QQ，设备和主机对时并记录误差。
相对该样本 `started_at` 的消息出现、图片开始显示、完整加载时间分别填入观察。
该起点包括 C 的静态准备；各 QQ API 的开始/结束另见调用记录中的 wall timestamp，
新增计时字段前的早期预检样本没有 wall timestamp，不从耗时反推或补造。
不要用 API 成功回执代替完整收图。人工未计时可以仅确认是否收到、渲染和重复数量，
时间字段保持 null，不能补造数字。

私有观察 JSON 的字段示例（数值仅作格式演示，不能直接作为实验结果）：

```json
{
  "device": "android", "received": true, "render_ok": true,
  "duplicates": 0, "clock_synced": false,
  "image_start_ms": null, "complete_ms": null, "message_ms": null,
  "clock_uncertainty_ms": null,
  "quota_before": null, "quota_after": null,
  "url_cache_observation": "unknown"
}
```

保存为0600文件，执行 `observe --sample 实验编号 --observation 私有文件路径`。
存在计时数据时必须提供 `clock_synced=true` 和录屏/人工计时误差；
额度前后值来自控制台，不以 B API 成功次数冒充真实额度变化。
同设备每样本仅一次观察，跨设备的相同重复消息不累计成两个重复事故。
首次与重复 URL、真实 TCP 建连与不可测连接状态、首次鉴权和缓存命中应分别比较。

`http_complete_ms` 是整个 HTTP await；trace 能观测 TCP（含 DNS）、TLS、
请求头/体写入、等待并读取响应头、响应体读取。JSON解码和客户端创建另计。
无法单独测连接池等待、纯 DNS 或精确首响应字节时明确列为不可测；
`receive_response_headers` 可以定位等待主要发生在哪个区间，但不是精确 TTFB。
trace 的 info 参数可能含敏感数据，回调完全忽略，只保留预设阶段、耗时与结果。

## 报告和生产决策

`report` 按模式、data/url、阶段、传输、连接状态和 URL 使用情况分组；
保留所有失败/未知尝试及样本数。未观察客户端、重复消息和额度时用 null，不用0冒充。
P50/P95/min/max 都从单条完整指标计算，少于20条的 P95 明确是描述性统计。
服务端 API、HTTP子阶段和客户端完整收图分开，不相加不同请求的阶段中位数。
`operation_total` 包含静态 GET 校验和实验记账；`api_ack` 是每条样本内 QQ API
调用完整耗时之和，不包含静态验证与调用间隙。C 的外网验证可能耗时数秒，
不能将其当作 Markdown 消息接口本身的耗时，也不能只看接口快就断言手机完整收图快。
定向验证命令：

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/current/bin/python -I \
  /home/sigaer/taiko-bot/tests/performance/test_qq_delivery_probe.py
```

推荐生产试点至少需要同条件可重复的约20% P50改善、P95不明显恶化、稳定客户端完整到图、
无重复/超时重发、主动权限与足够额度，以及正文/引用/按钮的功能差异说明。
C 还需 Markdown/反馈文字兼容和拟用场景的公开图片生命周期评估；
D 仅说明完全相同图片命中媒体凭据时可能省掉上传，不代表新图也能免上传。
自动生成报告保守保留 A，发布决定须人工审阅完整证据，工具不切换或部署新策略。

官方文档存在年代差异：[富媒体接口](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/rich-media.md)
仍有 `file_data` 未支持的旧说明，而[消息发送说明](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md)
含主动能力调整提示。文档用于理解风险，实际能力以本次目标 Bot/群的真实返回及客户端观察为准。
