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
  },
  "resumed_source_snapshots": {
    "protocol": {
      "commit": "883f911",
      "sha256": {
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
    },
    "performance": {
      "sha256": {
        "scripts/performance/qq_delivery/__init__.py": "37bc1ea6469ae380f89eec151b93d9e72c9a33260f2114ac085b012f2e0329a1",
        "scripts/performance/qq_delivery/config.py": "a59bb16d0ee609c8b3ba8b3541ba00eaa06e0636e070734fab9763aa2dbbfdf8",
        "scripts/performance/qq_delivery/events.py": "2a328d169fcadc70d1cb58bbbc18ee3d22215834383ea17a3e5bd4ca0e501180",
        "scripts/performance/qq_delivery/experiment.py": "14e88f32b9c980666de04a93688a7691288cd69ea2b25dbcf895dbcc7e55216c",
        "scripts/performance/qq_delivery/images.py": "da2ede2c36a4fad9bf7fad6aad87e46959a147e9f5e9bf012ba763b460962dcb",
        "scripts/performance/qq_delivery/report.py": "e0339fb444d6ff141a344acc2078e3ac1f1ac85f78d0e40ae3486efc0b647dda",
        "scripts/performance/qq_delivery/state.py": "e651f83ffc96b01ea76262b5de83febdb6f9cd697f151364ef46588fa4020025",
        "scripts/performance/qq_delivery/transport.py": "c46dec9c1b04ca5bd7d0fccc5a0fa313abc9d4977ede43fded4d3b691bff1824",
        "scripts/performance/qq_delivery_probe.py": "25738e0bc15483e700b202285ef15574903c169792be35414a5a802e03dac693"
      },
      "round_id": "performance-1"
    },
    "performance-2": {
      "round_id": "performance-2",
      "sha256": {
        "scripts/performance/qq_delivery/__init__.py": "37bc1ea6469ae380f89eec151b93d9e72c9a33260f2114ac085b012f2e0329a1",
        "scripts/performance/qq_delivery/config.py": "a59bb16d0ee609c8b3ba8b3541ba00eaa06e0636e070734fab9763aa2dbbfdf8",
        "scripts/performance/qq_delivery/events.py": "2a328d169fcadc70d1cb58bbbc18ee3d22215834383ea17a3e5bd4ca0e501180",
        "scripts/performance/qq_delivery/experiment.py": "14e88f32b9c980666de04a93688a7691288cd69ea2b25dbcf895dbcc7e55216c",
        "scripts/performance/qq_delivery/images.py": "da2ede2c36a4fad9bf7fad6aad87e46959a147e9f5e9bf012ba763b460962dcb",
        "scripts/performance/qq_delivery/report.py": "24428ee38ba2832eb3ad3c96dc20d87b49bf1ce0b9ac1eee042611480d498b53",
        "scripts/performance/qq_delivery/state.py": "e651f83ffc96b01ea76262b5de83febdb6f9cd697f151364ef46588fa4020025",
        "scripts/performance/qq_delivery/transport.py": "c46dec9c1b04ca5bd7d0fccc5a0fa313abc9d4977ede43fded4d3b691bff1824",
        "scripts/performance/qq_delivery_probe.py": "57524e55ad8ca5831f90605280861d283f6e1fd9cff397a411b2c4ea32138b60"
      }
    }
  },
  "source_snapshot_scope": "original archive hashes retained; resumed protocol and performance snapshots separately recorded"
}
```

主动权限、群授权、file_data/url 平台支持、Markdown 白名单与额度须以真实预检及控制台记录为准。

## 分组结果

|模式|阶段/传输/连接/URL|尝试|API成功率|API调用合计 P50 ms|API调用合计 P95 ms|Android完整收图 P50 ms|
|---|---|---:|---:|---:|---:|---:|
|A-data|performance/traced_httpx/new_connection/None|2|100.0%|2864.559|2974.24|None|
|A-data|performance/traced_httpx/new_connection/None|1|100.0%|3169.547|3169.547|None|
|A-data|protocol/adapter/unobservable/None|1|100.0%|2851.45|2851.45|None|
|B-data|performance/traced_httpx/new_connection/None|2|100.0%|2500.552|2540.688|None|
|B-data|protocol/adapter/unobservable/None|1|100.0%|3216.981|3216.981|None|
|B-url|performance/traced_httpx/new_connection/first_url|1|100.0%|2781.284|2781.284|None|
|B-url|performance/traced_httpx/new_connection/repeated_url|1|100.0%|2451.075|2451.075|None|
|B-url|protocol/traced_httpx/new_connection/repeated_url|1|100.0%|2584.589|2584.589|None|
|C|performance/traced_httpx/new_connection/repeated_url|4|100.0%|1938.303|2338.442|None|
|C|protocol/traced_httpx/new_connection/first_url|1|100.0%|3679.759|3679.759|None|
|D|performance/traced_httpx/new_connection/None|1|100.0%|2145.231|2145.231|None|
|D|protocol/adapter/unobservable/None|1|100.0%|2339.197|2339.197|None|

对照统计纳入 17 条记录；另有 4 条保留为审计证据，不纳入对照统计。
samples 保留全部 API 事实；comparison_eligible、cohort 和 trigger_source 标明统计范围与操作来源。管理员报告的额度下限单独保存，不当作实际扣减量。
API调用合计为每条样本内QQ API调用完整耗时之和，排除静态URL验证和调用间隙；包含准备与持久化的整步耗时另见 operation_total。
每模式成功率、最小/最大值、完整 API 子阶段、Windows 观察、重复发送、未知结果及主动额度见同目录 JSON。
未观察客户端或控制台额度的字段为 null，不以0代替。少于20个样本的 P95 只作描述。

## 阻塞条件

- client_full_load_timing_unmeasured
- active_quota_balance_change_unmeasured
- same_URL_first_and_cached_client_comparison_unmeasured
- small_unmatched_protocol_samples_are_not_performance_evidence

## 生产决策

证据不足时保持 A。当前不能证明主动上传即发送可以替代两阶段发送，不能判断它比 Markdown 更快，也不能确定实际收图最快的方案。
即使后续获得较低 API 延迟，仍需核对客户端完整加载、重复消息、主动额度、Markdown 渲染、文字/引用/按钮差异及隐私。
B 仅发送图片；C 测试资源为短时公开合成图片，这不构成发布私人 BXX 的许可。D 仅复用本 Bot、本测试群、同一合成图的有效媒体凭据。
工具不会自动推荐发布或切换策略；正式试点需达到至少约20%的可重复 P50 优势，P95不恶化并完成全部兼容性验收。

## 恢复实验与审计范围

按管理员纠正，仅保留第一轮 A、D，并从 C 重新开始；早先 B-data 的独立客户端确认另保留为能力预检。后续旧调用保留 API 事实，但不纳入对照统计。

旧 B-url 是测试工具实际执行的主动接口调用，并非模拟，也没有用户触发消息；没有传入伪造的被动 msg_id。其记录已明确排除。操作来源见 audit-provenance.json。

恢复后的 C 已确认图片、正文完整且无重复；B-url 和第一轮 A、D 也均确认完整且无重复。所有确认均未计时。

|样本|模式|轮次|纳入统计|API回执|客户端确认|
|---|---|---|---|---|---|
|825e621f81d2|B-data|initial_preflight|True|acknowledged|完整、无重复|
|336c737bfd06|A-data|initial_preflight|True|acknowledged|完整、无重复|
|edd2ecb1e48f|D|initial_preflight|True|acknowledged|完整、无重复|
|925bc641890a|A-data|excluded_after_initial_round|False|acknowledged|待观察|
|5b2f465a8dba|C|excluded_after_initial_round|False|blocked_before_send|待观察|
|2331c7738917|C|excluded_after_initial_round|False|acknowledged|待观察|
|050f7ae2e022|B-url|excluded_after_initial_round|False|acknowledged|待观察|
|ef89ae7fedaa|C|resumed_preflight|True|acknowledged|完整、无重复|
|50326757fbde|B-url|resumed_preflight|True|acknowledged|完整、无重复|
|e2d187ee1520|A-data|interleaved_performance|True|acknowledged|完整；重复数未确认|
|9ddf57a7c737|B-data|interleaved_performance|True|acknowledged|完整；重复数未确认|
|ecb70b97e182|C|interleaved_performance|True|acknowledged|完整；重复数未确认|
|e654254fa681|B-data|interleaved_performance|True|acknowledged|完整；重复数未确认|
|af29317a977c|C|interleaved_performance|True|acknowledged|完整；重复数未确认|
|91038a058bc8|A-data|interleaved_performance|True|acknowledged|完整；重复数未确认|
|b4ce981282e6|B-url|interleaved_performance|True|acknowledged|完整；重复数未确认|
|e6153c569b90|C|interleaved_performance|True|acknowledged|完整；重复数未确认|
|9450ac7b1fe5|A-data|interleaved_performance|True|acknowledged|完整；重复数未确认|
|bff7d618f110|D|interleaved_performance|True|acknowledged|完整；重复数未确认|
|e0bcfbb9a2ee|B-url|interleaved_performance|True|acknowledged|完整；重复数未确认|
|ddbf3e6b3481|C|interleaved_performance|True|acknowledged|完整；重复数未确认|

管理员报告剩余额度 900+，仅作为保守下限；实际主动额度扣减仍未知。生产 Bot 与发送策略未改变。
