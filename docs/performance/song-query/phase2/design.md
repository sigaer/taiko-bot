# 静态谱面 Manifest 与官方 QQ URL 路径

本方案基于第一阶段 `070442ef19afc1827a79aa542e092c50e27b0994`；不更换歌曲索引、匹配器或请求内 revision。Bot 0.24.0 的新功能默认关闭，不能据此认为已经生产验收或部署。

## 权利与资源边界

2026-11-13 用户明确答复真实谱面的公开范围为「全都允许」。这是本次本地谱面资源的操作授权依据；已有网站、下载包、OSS 链接本身不作为授权依据。发布者仍须生成 hash 绑定的逐项授权记录，以免后来加入的新来源被静默公开。策略记录留在运行目录，不能提交实际资源或私有配置。

审计发现每日更新从 taiko.wiki 下载到 `assets/fumens/<difficulty>/<id>.png`，同步 OSS 的键是 `fumen/<difficulty>/<id>.png`，现有键会随内容变化。补图器可能用本地 TJA 生成缺图。现有 Viewer `chart-image` 路由是按歌曲/难度取图，ETag 包含文件属性，也不是内容版本 URL。本阶段不修改 Viewer 的公共数据 Manifest、总资源包或这些 API；新文件是 Bot 专属的本地可选元数据。

## 固定协议

本地 `songs/static_fumen_policy.json`：

```json
{
  "schema": 1,
  "scope": "public-static-fumen",
  "base_url": "https://static.example.test/approved",
  "valid_until": 1900000000,
  "grants": [{
    "difficulty": "Oni", "song_id": "649", "public": true,
    "sha256": "<64 lowercase hex>", "authorization_ref": "<explicit grant reference>"
  }]
}
```

本地 `songs/static_fumen_manifest.json`：

```json
{
  "schema": 1, "policy_sha256": "<policy bytes SHA-256>",
  "checked_at": 1899999700, "valid_until": 1900000000,
  "resource_version": "<canonical policy hash + entries SHA-256>",
  "entries": [{
    "difficulty": "Oni", "song_id": "649", "width": 816, "height": 1648,
    "sha256": "<64 lowercase hex>", "resource_version": "<same content hash>",
    "url": "https://static.example.test/approved/sha256/<same content hash>.png"
  }]
}
```

策略期限最多 366 天；Manifest 健康有效期最多 900 秒，离线发布器默认 300 秒。无常驻无限结果缓存。相同文件内容得到相同 URL；Manifest 的总版本包含 policy 摘要和排序后的 entries，不包含刷新时间。

URL 白名单由 `TAIKO_STATIC_FUMEN_BASE_URL` 固定精确 HTTPS origin 和路径前缀。条目 URL 必须严格等于该前缀加 `/sha256/<sha256>.png`。拒绝 HTTP、用户信息、query、fragment、百分号编码、路径穿越和不同域名/目录。歌曲 ID 为规范正整数，难度限定五个既有目录。元数据固定文件名、拒绝 symlink、使用 O_NOFOLLOW 读取，有字节数、条目数、图像尺寸上限；不把 Manifest 中的任意路径当作本地路径。

## 离线发布顺序

1. 读取并校验显式 policy；未授权的文件不复制到公开目录。
2. 在专用、带所有权标记的发布目录中准备 PNG；验证格式、解码、尺寸和源文件 SHA-256。
3. 同目录临时文件写入/fsync 后原子替换到内容哈希路径，流式复制再次核对 hash，禁止同一 URL 对应不同字节。
4. 对最终 HTTPS URL 执行完整 GET，禁止重定向，校验 200、image/png、字节数、SHA-256。不是 HEAD。
5. 缺失、损坏、hash 不符、未授权、HTTP 不可达、内容不符的条目不进入新 Manifest；再次核对 policy 未变化。
6. fsync 元数据临时文件，`os.replace` 原子切换 Manifest，再 fsync 所在目录。发布失败不写半份 Manifest；致命失败保留旧文件。

发布模块为 `python -m taiko_bot.offline.static_fumens --root <isolated-runtime> --publication-root <dedicated-directory> --base-url <pinned-https-base>`，需通过 memory QA runner。没有启动任务、定时器、每日更新自动接入或生产配置修改。本阶段真实测试只使用独立测试命名空间的一张已授权谱面。

运行期 policy 与 Manifest 不匹配时立即失效；即使旧 Manifest 还在，撤权也不能继续使用。元数据签名变化触发重载，每 30 秒还会重读核对两份内容哈希；字节未变且 lease 有效时复用 map，不重新解析 JSON。过期检查逐次执行。运行期持有的 map/entry 不可变，锁内准备并一次切换；损坏、缺失、过期、撤权均清空静态快照并回退，不保留过期授权。

HTTPS 校验只证明发布时资源可访问，无法保证有效期内绝无网络故障。查询路径不作远程探测；有效期到期则回退。生产上线前需另行安排小于 lease 的离线续期、可用性监控和旧哈希资源保留：保留至少覆盖旧 Manifest lease、在途消息及业务允许的客户端缓存窗口。当前没有自动垃圾回收，不删除仍可能被旧消息引用的正式静态资源。测试资产的清理仅作用于测试自有命名空间，不改变 30 分钟图片缓存。

## 查询与发送

```text
命令解析 → 原快照查歌 → 原 brief/难度/模糊提示
  → 官方 QQ + 有效 Manifest 命中 → SDK Markdown(URL, 宽高) → 原 QQ 发送规则
  → 其他情况 → 原谱面读取与图片回复
```

静态命中不检查 PNG、不打开 PNG、不解码图片、不生成随机缓存文件。OneBot 不读取静态 Manifest，保留原消息构造。普通、模糊、难度前缀及中心/客户端差异交由第一阶段原解析/索引处理。

构造 Markdown 失败可在发送前回退；开始发送后，超时、未知结果及异常直接向上传递，不能补发文字或图片。已明确识别的官方被动配额错误 40034128 继续服从原中心端主动发送规则，不扩大主动权限；客户端不新增主动补发。BXX、动态图片、全局 qq_images、通用缓存 TTL 和清理任务完全不变。

## 启动预热

`TAIKO_SONG_QUERY_PREWARM=1` 时 NoneBot startup hook 用 `asyncio.to_thread(provider.get_snapshot)` 预先加载原快照；默认关闭。失败只记录异常类型，保留下一次惰性加载恢复。线程准备仍可能争用 GIL；预热不替代每 30 秒复核与后续更新，也不解决同步模糊匹配。具体阻塞风险见独立性能报告，不以此宣称事件循环无阻塞。

## 生产前验收边界

隔离测试同时覆盖实际安装的官方 QQ/OneBot SDK 消息模型和本地 TLS 发布。真实 QQ 测试只复用既有私有目标，用全新的被动事件，写前预留，最多三次，未知结果停止。API ACK 与客户端显示分开记录。用户确认本轮三图各收到一次、正常显示；没有提供客户端型号和显示计时。OneBot 终端实测、QQ 客户端首次/重复显示耗时、长期资源可用性及并发阻塞风险仍须有对应证据。未完成的项保持 PENDING；不得以回放测试替代生产前验收，不合并、不部署。
