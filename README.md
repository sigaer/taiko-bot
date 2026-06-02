# taiko-bot

`taiko-bot` 是一个面向《太鼓达人》查询与同步场景的 NoneBot 项目，支持 OneBot V11，并依赖 `viewer.sakura-bot.cn` 提供的公共数据、资源包和中心接口。

## 1. 环境要求

- Python `3.11` 推荐
- Windows、Linux、macOS 均可运行
- 一个可直连的 OneBot V11 客户端
- 可访问 `https://viewer.sakura-bot.cn`

## 2. 安装项目

### Windows PowerShell

```powershell
cd C:\path\to\taiko-bot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
Copy-Item .env.example .env
```

### Linux / macOS

```bash
cd /path/to/taiko-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
cp .env.example .env
```

如果本机还没有 Python 3.11，可先从 `https://www.python.org/downloads/` 安装，或使用系统包管理器安装。

## 3. 配置 `.env`

至少需要确认以下配置：

```env
HOST=0.0.0.0
PORT=37564
TAIKO_LOCAL_DATA_API_HOST=127.0.0.1
TAIKO_LOCAL_DATA_API_PORT=37565
TAIKO_VIEWER_BASE_URL=https://viewer.sakura-bot.cn
TAIKO_VIEWER_DEVELOPER_TOKEN=你的开发者token
```

常用配置项说明：

- `HOST` / `PORT`：单进程 `nb run` 的监听地址
- `TAIKO_CORE_HOST` / `TAIKO_CORE_PORT`：Core 模式监听地址
- `TAIKO_GATEWAY_HOST` / `TAIKO_GATEWAY_PORT`：Gateway 模式监听地址
- `TAIKO_LOCAL_DATA_API_HOST` / `TAIKO_LOCAL_DATA_API_PORT`：本地数据 API 监听地址
- `TAIKO_PUBLIC_DATA_BASE_URL`：公共 JSON 数据接口基址
- `TAIKO_VIEWER_BASE_URL`：viewer 服务基址
- `TAIKO_VIEWER_DEVELOPER_TOKEN`：访问中心受限接口所需的开发者 token
- `QQ_MARKDOWN_IMAGE_BASE_URL`：QQ Markdown 图片缓存基址

## 4. 首次启动行为

bot 首次启动时会自动：

1. 拉取公共 JSON 数据到 `songs/`
2. 检查 `assets/.bundle.sha256`
3. 在资源缺失或版本变化时自动下载并解压最新资源包到 `assets/`
4. 按需缓存用户成绩到 `storage/cache/userdata/`
5. 按需缓存地图快照到 `storage/data/arcade_map_cache/`

如果本地没有可用资源且资源包下载失败，启动会失败；如果本地已有资源，则会继续使用现有资源。

## 5. 启动本地数据 API

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

默认地址：

- `http://127.0.0.1:37565`

主要接口：

- `GET /health`
- `POST /v1/public/sync`
- `POST /v1/arcades/sync`
- `GET /v1/arcades/query?city=鞍山`
- `GET/PUT /v1/runtime/multi-bind`
- `GET/PUT /v1/runtime/draw-guess`
- `GET/PUT /v1/userdata/{user_id}`
- `GET /v1/userdata/{user_id}/history`

## 6. 启动 Bot

### 方式 A：单进程

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
nb run
```

Linux / macOS：

```bash
source .venv/bin/activate
nb run
```

### 方式 B：Core / Gateway 双进程

Windows PowerShell：

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

Linux / macOS：

```bash
source .venv/bin/activate
./scripts/start_taiko_gateway_core.sh
```

## 7. 连接 OneBot 客户端

无论使用单进程还是 Gateway 模式，OneBot V11 客户端都连接到：

- `ws://127.0.0.1:37564/onebot/v11/ws`

如果你修改了 `.env` 中的端口，请同步替换这里的地址。

## 8. 主要功能

- 成绩更新：`taikoupdate`、`更新广场`、`更新hiroba`
- 成绩查询：`b30`、进度图、查分、总结图、词云
- 地图查询：`xx哪有鼓`
- 绑定与多账号：绑定、切换账号、多号合并读取
- 本地运行接口：公共数据同步、地图同步、运行态存储、用户缓存历史
