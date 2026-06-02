# taiko-bot

`taiko-bot` 是一个面向《太鼓达人》查询与同步场景的 NoneBot 项目，支持 OneBot V11，并依赖 `viewer.sakura-bot.cn` 提供公共数据、资源包和中心代理接口。

## 1. 环境要求

- Python `3.11` 推荐
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
python -m pip install -e .
cp .env.example .env
```

如果本机还没有 Python 3.11，可先从 `https://www.python.org/downloads/` 安装，或使用系统包管理器安装。

## 3. 配置 `.env`

最少需要确认这些配置：

```env
HOST=0.0.0.0
PORT=37564
TAIKO_VIEWER_BASE_URL=https://viewer.sakura-bot.cn
TAIKO_VIEWER_DEVELOPER_TOKEN=
```

### 必填/常用项

- `HOST` / `PORT`
  - bot 主服务监听地址。
  - OneBot V11 客户端默认连接 `ws://127.0.0.1:37564/onebot/v11/ws`。
- `TAIKO_VIEWER_BASE_URL`
  - viewer 服务地址。
  - 默认是 `https://viewer.sakura-bot.cn`。
- `TAIKO_VIEWER_DEVELOPER_TOKEN`
  - 用于访问 viewer 的受限代理接口。
  - 这些能力依赖它：`taikoupdate`、`更新hiroba`、中心成绩读取、鼓众玩家资料/排行榜等。
  - 如果留空，bot 仍可拉取公开曲库和资源包，但账号成绩相关功能会不可用或退化。
  - 第一次只想验证 bot 是否能启动，可以先留空；后续需要成绩相关功能时再填写。

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
3. 在资源缺失或版本变化时自动下载并解压最新资源包到 `assets/`
4. 按需缓存用户成绩到 `storage/cache/userdata/`
5. 按需缓存地图快照到 `storage/data/arcade_map_cache/`

如果本地没有可用资源且资源包下载失败，启动会失败；如果本地已有资源，则会继续使用现有资源。

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
- `GET/PUT /local-api/v1/runtime/multi-bind`
- `GET/PUT /local-api/v1/runtime/draw-guess`
- `GET/PUT /local-api/v1/userdata/{user_id}`
- `GET /local-api/v1/userdata/{user_id}/history`

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
- 绑定与多账号：绑定、切换账号、多号合并读取
- 本地维护接口：公共数据同步、地图同步、运行态存储、用户缓存历史
