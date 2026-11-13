# QQ 官方图片发送实验

本报告由独立测试工具生成；生产 BXX 发送策略保持不变。

## 环境与能力预检

```json
{
  "packages": {
    "taiko-bot": "0.22.1",
    "taiko-application": "0.9.1",
    "nonebot2": "2.5.0",
    "nonebot-adapter-qq": "1.7.3",
    "httpx": "0.28.1",
    "httpcore": "1.0.9",
    "Pillow": "11.3.0"
  },
  "python": "3.11.4",
  "installed_source_sha256": {
    "qq_api_builders": "a4e85e6f112faa9d363ad1cbb6dd670119bd5042f2cea83e4c49f77659a53aab",
    "httpx_driver_session": "37852b42ae377c070acd9e1a661f37395552bda02b6768044829a4d905a3d6ac"
  },
  "post_group_files": "(self, *, group_openid: str, file_type: Optional[Literal[1, 2, 3, 4]] = None, url: str | None = None, srv_send_msg: bool = True, file_data: str | bytes | None = None, upload_id: str | None = None) -> nonebot.adapters.qq.models.qq.PostGroupFilesReturn",
  "post_group_messages": "(self, *, group_openid: str, msg_type: Literal[0, 1, 2, 3, 4, 7], content: str | None = None, markdown: nonebot.adapters.qq.models.common.MessageMarkdown | None = None, keyboard: nonebot.adapters.qq.models.common.MessageKeyboard | None = None, media: nonebot.adapters.qq.models.qq.Media | None = None, ark: nonebot.adapters.qq.models.common.MessageArk | None = None, embed: nonebot.adapters.qq.models.common.MessageEmbed | None = None, image: None = None, message_reference: nonebot.adapters.qq.models.common.MessageReference | None = None, event_id: str | None = None, msg_id: str | None = None, msg_seq: int | None = None, timestamp: int | datetime.datetime | None = None) -> nonebot.adapters.qq.models.qq.PostGroupMessagesReturn",
  "source": "installed_environment",
  "adapter_httpx_connection_policy": "installed driver creates one Session/AsyncClient per request; no shared HTTP pool",
  "file_data": "accepted by installed signature; platform support requires live preflight",
  "upload_response_id": "installed PostGroupFilesReturn omits id; probe inspects raw response for presence only",
  "main_at_experiment_start": "2efeff1",
  "production_release": "/opt/taiko-bot/releases/0.22.1",
  "probe_source_sha256": {
    "scripts/performance/qq_delivery/__init__.py": "37bc1ea6469ae380f89eec151b93d9e72c9a33260f2114ac085b012f2e0329a1",
    "scripts/performance/qq_delivery/config.py": "a59bb16d0ee609c8b3ba8b3541ba00eaa06e0636e070734fab9763aa2dbbfdf8",
    "scripts/performance/qq_delivery/events.py": "2a328d169fcadc70d1cb58bbbc18ee3d22215834383ea17a3e5bd4ca0e501180",
    "scripts/performance/qq_delivery/experiment.py": "3a4a3546566093284bba7194895c2e64bb2049698b462ebf18ce1549c43ad068",
    "scripts/performance/qq_delivery/images.py": "da2ede2c36a4fad9bf7fad6aad87e46959a147e9f5e9bf012ba763b460962dcb",
    "scripts/performance/qq_delivery/report.py": "a95c4eda64a3930b96d95c2c0ebd3acc14ee8ec4f2dd918ee6842929712a489a",
    "scripts/performance/qq_delivery/state.py": "787ae3884ebda87cd400d6eca1928184b96d809989eba2662ff106fedefc3861",
    "scripts/performance/qq_delivery/transport.py": "c46dec9c1b04ca5bd7d0fccc5a0fa313abc9d4977ede43fded4d3b691bff1824",
    "scripts/performance/qq_delivery_probe.py": "25738e0bc15483e700b202285ef15574903c169792be35414a5a802e03dac693"
  }
}
```

主动权限、群授权、file_data/url 平台支持、Markdown 白名单与额度须以真实预检及控制台记录为准。

## 分组结果

|模式|阶段/传输/连接/URL|尝试|API成功率|API调用合计 P50 ms|API调用合计 P95 ms|Android完整收图 P50 ms|
|---|---|---:|---:|---:|---:|---:|
|A-data|protocol/adapter/unobservable/None|1|100.0%|2851.45|2851.45|None|
|A-data|protocol/traced_httpx/new_connection/None|1|100.0%|3227.457|3227.457|None|
|B-data|protocol/adapter/unobservable/None|1|100.0%|3216.981|3216.981|None|
|B-url|protocol/traced_httpx/new_connection/first_url|1|100.0%|2847.591|2847.591|None|
|C|protocol/traced_httpx/new_connection/repeated_url|1|100.0%|3582.4|3582.4|None|
|C|protocol/traced_httpx/unobservable/first_url|1|未调用|None|None|None|
|D|protocol/adapter/unobservable/None|1|100.0%|2339.197|2339.197|None|

API调用合计为每条样本内QQ API调用完整耗时之和，排除静态URL验证和调用间隙；包含准备与持久化的整步耗时另见 operation_total。
每模式成功率、最小/最大值、完整 API 子阶段、Windows 观察、重复发送、未知结果及主动额度见同目录 JSON。
未观察客户端或控制台额度的字段为 null，不以0代替。少于20个样本的 P95 只作描述。

## 阻塞条件

- protocol_only_not_10_to_20_sample_benchmark
- client_full_load_timing_unmeasured
- active_quota_balance_change_unmeasured
- same_URL_first_and_cached_client_comparison_unmeasured

## 生产决策

证据不足时保持 A。当前不能证明主动上传即发送可以替代两阶段发送，不能判断它比 Markdown 更快，也不能确定实际收图最快的方案。
即使后续获得较低 API 延迟，仍需核对客户端完整加载、重复消息、主动额度、Markdown 渲染、文字/引用/按钮差异及隐私。
B 仅发送图片；C 测试资源为短时公开合成图片，这不构成发布私人 BXX 的许可。D 仅复用本 Bot、本测试群、同一合成图的有效媒体凭据。
工具不会自动推荐发布或切换策略；正式试点需达到至少约20%的可重复 P50 优势，P95不恶化并完成全部兼容性验收。

## 本次真实预检（2026-11-13）

主分支起点 `2efeff1`；生产 Bot 0.22.1 / Application 0.9.1。SDK 为 QQ Adapter 1.7.3、NoneBot 2.5.0、HTTPX 0.28.1 / HTTPcore 1.0.9。
测试图1080×2436 JPEG，517045字节（约505 KiB），同一合成图复用。下表为单条观测，单位秒；不同传输路径分别保留。

|模式 / 传输|真实发图步骤|上传API|消息API|QQ API调用合计|含校验/记账整步|
|---|---:|---:|---:|---:|---:|
|B-data / adapter|1|3.217|0.000|3.217|3.232|
|A-data / adapter|1|0.939|1.913|2.851|2.869|
|D / adapter|1|0.000|2.339|2.339|2.349|
|A-data / traced_httpx|1|1.037|2.191|3.227|3.249|
|C / traced_httpx|1|0.000|3.582|3.582|4.229|
|B-url / traced_httpx|1|2.848|0.000|2.848|2.988|

所有6条发图步骤均有HTTP成功及消息ID存在性回执；共8次发图业务API调用，不含Token获取。A有两条不同传输路径，不能合并当成同条件中位数。
B-data和B-url都实际接受了主动上传；平台返回TTL为86400秒。D复用了成功A的凭据，发送前实验租期剩余1744秒，没有重复上传。
主动API共2次，控制台实际额度变化未知。已明确观察B-data在Android完整收到且无重复；其余客户端结果仍待录入，所有客户端完整收图时间均未测。

消息发送样本 `925bc641890a` 的HTTP完整调用2182.421毫秒，其中等待并读取响应头2154.738毫秒（约98.7%）；TCP（含DNS）9.398毫秒、TLS8.841毫秒。
这支持主要等待发生在响应头返回前，不能进一步证明是腾讯审核、限流或某个服务端步骤，也不是精确首字节测量。

C额外有一次静态校验失败，尚未调用QQ；诊断发现QA umask077产生目录0700/JPEG0600，HTTPS返回404。修复仅作用于隔离合成图目录，之后外网验证成功。该失败保留在qq-delivery-errors.json，不计为一次QQ发送失败。
成功C的本地缓存准备8.705毫秒、外网完整校验623.276毫秒、Markdown API3582.400毫秒。客户端实际完整加载尚未计时，不能据API回执比较手机收图。

本次没有完成10～20次交错性能测试、同一URL首次/客户端缓存对照、同步录屏和Windows交叉验证。P95均为小样本描述；首次鉴权、正常鉴权缓存和每请求新HTTP连接分别记录。
公网合成JPEG已由独立清理任务删除，收尾检查剩余0个；最后测试URL在清理后HTTP状态为404。清理timer已停止并禁用，实验状态已暂停。既有CDN/客户端缓存可能保留约30分钟，不声称已做全网缓存清除。
生产Bot仍为同一PID2458833、active、自动重启0；没有发布Bot或切换发送策略。运行环境和收尾证据见audit-context.json。

明确结论：B主动接口当前可用，但样本量、客户端时间和额度证据不足，且不能携带原有正文/引用/按钮，暂不替代A；B-url与Markdown的实际收图快慢未定；当前不能选出完整收图最优方案。D仅对同一图片命中有效凭据有意义。暂不单独发布发送策略新版本。
