# taiko-bot

`taiko-bot` 是一个面向《太鼓达人》查询与同步场景的 NoneBot 项目，支持 OneBot V11，并依赖 `viewer.sakura-bot.cn` 提供公共数据、资源包和中心代理接口。

项目许可：`GPL-2.0-only`。完整文本见仓库根目录 [LICENSE](/home/sigaer/taiko-bot/LICENSE)。

## 用户说明

- [手动成绩账号使用说明](docs/manual-score-accounts.md)

## 1. 环境要求

- Python `3.11` 或以上（当前主要测试版本为 3.11）
- 实际可安装范围以 `pyproject.toml` 为准
- Windows、Linux、macOS 均可运行
- 一个可直连的 OneBot V11 客户端
- 可访问 `https://viewer.sakura-bot.cn`

## 2. 获取代码并安装

### Windows PowerShell

```powershell
git clone https://github.com/sigaer/taiko-bot.git
Set-Location .\taiko-bot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements-domain.txt
python -m pip install -e .
Copy-Item .env.example .env
```

### Linux / macOS

```bash
git clone https://github.com/sigaer/taiko-bot.git
cd taiko-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-domain.txt
python -m pip install -e .
cp .env.example .env
```

如果本机还没有 Python 3.11，可先从 `https://www.python.org/downloads/` 安装，或使用系统包管理器安装。

领域依赖固定为 `sakura-taiko-core==0.1.2` / `sakura-taiko-contract==0.1.0`。
`requirements-domain.txt` 使用固定 Git revision，安装需要 Git、GitHub SSH 读取权限，
以及这两个私有依赖仓库的授权。没有仓库读取权限时，向维护者获取这两个版本的 wheel，
先运行 `python -m pip install <contract-wheel> <core-wheel>`，再安装本项目。
不要用其他版本替代；启动会检查依赖版本。
详细的验证、版本和回退说明见 [Phase 4 记录](docs/taiko-domain-extraction/phase4-client.md)。

## 3. 配置 `.env`

最少需要确认这些配置：

```env
HOST=0.0.0.0
PORT=37564
TAIKO_VIEWER_BASE_URL=https://viewer.sakura-bot.cn
TAIKO_VIEWER_DEVELOPER_TOKEN=
TAIKO_BOT_SERVICE_TOKEN=
```

### 必填/常用项

- `HOST` / `PORT`
  - bot 主服务监听地址。
  - OneBot V11 客户端默认连接 `ws://127.0.0.1:37564/onebot/v11/ws`。
- `TAIKO_VIEWER_BASE_URL`
  - viewer 服务地址。
  - 默认是 `https://viewer.sakura-bot.cn`。
- `TAIKO_VIEWER_DEVELOPER_TOKEN`
  - 私有成绩读取、历史、Wahlap 更新、Hiroba 同步、Hiroba 凭据状态/绑定和 QQ 绑定读取/写入/切换必须配置有效 token。
  - 请求使用 `Authorization: Bearer <token>`，每日额度与成绩授权分别核验。
  - 普通 token 可读取其 Viewer 账号自有绑定；跨账号服务需要私有运维按 token 登记 `source_read`、`history_read`、`wahlap_update`、`hiroba_sync` 和明确 Source 范围。
  - 在 Viewer Phase 6 最终激活前完成服务授权登记；登记流程见 Viewer 的 `docs/taiko-domain-extraction/source-service-operations.md`。
  - QQ 中心服务另需 `bind_read`、`bind_write`、`bind_current`；删除和可见性分别需 `bind_remove`、`bind_visibility`，旧写权限不会自动取得删除权限。须显式登记 `principals`，Source 范围必须包含该身份的全部绑定。身份格式为裸数字 QQ、`onebot_v11:QQ` 或 `qq_official:openid`，不同格式分别授权。
  - QQ 历史迁移另需 `bind_migrate`。用原 QQ 私聊旧 bot 发送 `迁移验证码`，再私聊目标 bot 发送 `绑定QQ QQ号 验证码`。迁移接口只接受 canonical `onebot_v11:QQ` / `qq_official:openid`；服务授权须覆盖原绑定和目标已有全部 Source。验证码十分钟有效，申请不自动重试；消费重试固定同一码/目标，不恢复后来删除的绑定。客户端不再读本地 SQLite/JSON 作为 QQ 迁移依据。
  - 普通 token 的 QQ 绑定访问要求 Viewer 账号已验证该 QQ；添加账号还要求自有同来源绑定。切换和添加 SDK 可传 `request_id`，同一凭据/授权/意图重试返回当前绑定，不重复修改或覆盖后来选择。
  - Hiroba 凭据状态另需 `hiroba_credential_status`；绑定需 `hiroba_bind`、明确 Source/`principals` 范围。普通 token 绑定要求已有自有 Hiroba 绑定；跨账号服务覆盖发现的全部卡片及 QQ 的已有全部成员。密码仅经 HTTPS 请求体及中心私有 stdin，不进入 worker argv。
  - Hiroba 凭据绑定 SDK 支持可选 `request_id`，等待上限 300 秒；同一授权及意图的已提交重试跳过登录、重复写入和重置后来选择。公共曲库、公开 Wahlap 玩家资料和排行榜保持原调用用途；缓存授权与其余 Phase 6 激活条件仍须完成。
  - Hiroba 同步最多等待 900 秒；上游数据量及冷却规则沿用中心实现。
- `TAIKO_BOT_SERVICE_TOKEN`
  - 用于创建、认领和维护手动成绩账号，必须与 viewer 的同名配置一致。
  - 它不是开发者额度 token；未配置时仅手动账号写命令不可用。
  - 不要将真实值提交到仓库。

### QQ 官方机器人相关

- `QQ_IS_SANDBOX`
  - 仅在你接入 QQ 官方机器人时使用。
  - `true` 表示沙箱环境，`false` 表示正式环境。
- `QQ_BOTS`
  - 仅在你接入 QQ 官方机器人时填写。
  - 它是一个 JSON 数组，每个元素表示一个 QQ 官方机器人应用。
  - 常见字段：
    - `id`：AppID
    - `token` / `secret`：官方后台分配的凭据
    - `use_websocket`：是否启用 QQ 官方 WebSocket
    - `intent`：事件订阅开关
  - `.env.example` 中保留了一条可直接改值的示例。
- `QQ_MARKDOWN_IMAGE_BASE_URL`
  - 仅在你使用 QQ 官方机器人，并希望发送 Markdown 图片消息时需要关注。
  - bot 会把图片缓存到本地输出目录，再通过这个公开地址让 QQ 侧访问。
  - 如果你自建 viewer 域名，需要把它改成你自己的公开地址，并确保该地址能访问图片缓存目录。

### 其他按需项

- `BOT_GROUP_WHITELIST_PATH`
  - 仅在你希望限制 bot 只在部分群启用时填写。
  - 指向一个 JSON 文件，格式示例：
```json
{
  "123456789": ["987654321", "1122334455"]
}
```
  - 含义是：bot 账号 `123456789` 仅在这些群号内启用。
- `TAIKO_CORE_HOST` / `TAIKO_CORE_PORT` / `TAIKO_GATEWAY_HOST` / `TAIKO_GATEWAY_PORT`
  - 仅在你使用 Core / Gateway 双进程模式时需要。
- `TAIKO_LOCAL_DATA_API_HOST` / `TAIKO_LOCAL_DATA_API_PORT`
  - 仅在你打算把本地维护接口单独起成第二个进程时需要。
  - 默认单进程部署不需要改。

## 4. 首次启动行为

首次启动时会自动：

1. 拉取公共 JSON 数据到 `songs/`
2. 检查 `assets/.bundle.sha256`
3. 在资源缺失或版本变化时自动后台下载并解压最新资源包到 `assets/`
4. 按需同步地图快照到 `storage/data/arcade_map_cache/`

说明：

- 绑定、当前槽位、成绩、历史都以 viewer 中心为准。
- bot 本地不再把 `storage/cache/userdata/`、`taiko_multi_bind.json` 这类文件当作权威数据源。
- 首次完整资源同步在普通网络环境下可能接近 15 分钟。
- bot 进程会先启动；资源未就绪时，图片类功能会提示稍后再试，不会因为大资源包下载而卡死整个启动流程。

## 5. 启动 Bot

默认推荐单进程启动，不需要先单独启动本地数据 API。

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
python .\bot.py
```

### Linux / macOS

```bash
source .venv/bin/activate
python bot.py
```

启动后：

- OneBot V11 WebSocket 地址：
  - `ws://127.0.0.1:37564/onebot/v11/ws`
- 同进程本地维护接口地址：
  - `http://127.0.0.1:37564/local-api/health`
  - `http://127.0.0.1:37564/local-api/v1/public/sync`
  - `http://127.0.0.1:37564/local-api/v1/arcades/query?city=鞍山`

### 关于 `nb run`

- 默认不需要 `nb run`。
- Windows 下如果直接调用系统全局 `nb`，可能会误用全局 Python 环境，触发 `redis.asyncio` 缺失这类与 bot 本体无关的依赖错误。
- 如果你确实想用 `nb run`，请确保使用当前虚拟环境里的 `nb`：

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\nb.exe run
```

## 6. 本地维护接口

默认已经合并进 bot 进程，挂载路径是 `/local-api`，平时不需要单独启动。

常用接口：

- `GET /local-api/health`
- `POST /local-api/v1/public/sync`
- `POST /local-api/v1/arcades/sync`
- `GET /local-api/v1/arcades/query?city=鞍山`
- `GET /local-api/v1/userdata/{user_id}`
- `GET /local-api/v1/userdata/{user_id}/history`
- `GET/PUT /local-api/v1/runtime/draw-guess`

成绩与历史 GET 要求调用者自己的 `Authorization: Bearer <token>`；中心核验该凭据的 Source 权限。本地接口不会替匿名请求使用配置中的 Bot 服务 token。

私有读取每次访问中心；精确条件 GET 可在完整授权复核后确认缓存内容。内存缓存按中心地址、凭据哈希、Source 和 current/history 隔离，最多64项、总计32MiB、单项4MiB、存活30秒。过期强制重新获取，任何401/403/429/503或连接失败均拒绝旧缓存；不把成绩写入普通Source-ID磁盘缓存。需要同时使用成绩和历史的加载器核对同一个已验证发布版本，变化时最多重试一次。

客户端 0.2.4 的私有历史加载器请求 `?format=raw-v1`，需要中心 Viewer 0.82.0 的已激活服务。Phase 6 中的仓库提交是激活前准备，当前线上版本仍须以部署台账为准。默认 SDK 历史 DTO 保持兼容；新私有加载器拒绝缺少排序元数据的非空历史。`fileName` 与捕获的文件时间只保留旧排序语义，不表示游玩时间或测量事实；u0 使用带微秒的合并配方名称，不伪造磁盘时间。趋势、更新图、B30 和当前段位进度由中心历史重建，B30/更新图/当前段位使用同一 current/history 版本；本地查询 token 在读取前后复核。旧本地成绩写入及原生 Hiroba 同步入口返回410，现有命令继续使用中心代理。

u0 读取由中心合并全部成员，客户端不写本地合并成绩。内部 `u0v1_` 标识完整编码 Bot principal，保留官方身份中的大小写、下划线和尾部字符。中心必须证明 principal 的 `bind_read` 与所有成绩成员的 `source_read`；u0 历史还需所有成员的 `history_read`，因为历史包含当前观察点。普通账号须有已验证 QQ 与完整自有成绩绑定。合并发布标识包含全部成员的版本及绑定/profile 选择，与单成员标识分别验证。

以下接口已经停用，会返回 `410 Gone`：

- `GET/PUT /local-api/v1/runtime/multi-bind`
- `PUT /local-api/v1/userdata/{user_id}`

如果你确实需要把它单独起成第二个进程：

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn taiko_data_api:app --host 127.0.0.1 --port 37565
```

### Linux / macOS

```bash
source .venv/bin/activate
./scripts/start_local_data_api.sh
```

## 7. Core / Gateway 双进程模式

只有在你明确需要 Core / Gateway 分离部署时再使用这一模式。

### Windows PowerShell

终端 1：

```powershell
.\.venv\Scripts\Activate.ps1
$env:BOT_POOL_METRICS_SERVICE_NAME="taiko"
python -m uvicorn bot_core:app --host 127.0.0.1 --port 37563
```

终端 2：

```powershell
.\.venv\Scripts\Activate.ps1
$env:ONEBOT_GATEWAY_SERVICE_NAME="taiko"
$env:ONEBOT_GATEWAY_CORE_WS_URL="ws://127.0.0.1:37563/onebot/v11/ws"
$env:ONEBOT_GATEWAY_CORE_HTTP_URL="http://127.0.0.1:37563"
$env:ONEBOT_GATEWAY_ALLOW_CROSS_HOST_TAKEOVER="1"
$env:ONEBOT_GATEWAY_DUPLICATE_TAKEOVER_IDLE="0"
python -m uvicorn bot_gateway:app --host 0.0.0.0 --port 37564
```

### Linux / macOS

```bash
source .venv/bin/activate
./scripts/start_taiko_gateway_core.sh
```

## 8. 主要功能

- 成绩更新：`taikoupdate`、`更新广场`、`更新hiroba`
- 成绩查询：`b30`、进度图、查分、总结图、词云
- 地图查询：`xx哪有鼓`
- 绑定与多账号：绑定、切换账号；当前槽位由 viewer 中心统一维护
- 本地维护接口：公共数据同步、地图同步、运行态存储、中心数据代理查询

网页成绩 token 仅在私聊中为发送者的中心当前实账号签发，服务需显式 `score_token_issue` scope、principal 及全部绑定 Source 授权。隐藏的自有账号可用，u0/手动/他人绑定拒绝。签发 POST 不自动重试；再次发送命令会生成新 token 并使旧 token 失效。旧本地 bearer helper 已停用。客户端 0.2.6 需与 Viewer 0.82.0 中心协议一起激活。

### 公共曲目插件归属切换候选（Phase 2F-B）

本功能分支由同一外部插件统一注册 `xx是什么歌`、别名、三类位置、难度 ID 与物量查询；安装客户端前须先准备
Application 0.5.0 与 `nonebot-plugin-taiko-song` 0.2.0 的 wheel。
[安装顺序、宿主配置和验收边界](packages/nonebot-plugin-taiko-song/README.md)。
客户端仍固定 Core 0.1.2 / Contract 0.1.0，其他私人命令保持 main 已合并的授权热修补。
