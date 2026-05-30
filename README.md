# taiko-bot

`taiko-bot` 是从原私有 `taiko` 运行栈中抽离出的独立 NoneBot 项目，只保留 bot 运行逻辑，不包含歌曲库、资源图包、用户成绩、cookie 等私有数据。

## 1. 环境要求

- Python `3.11` 推荐
- Linux/macOS 推荐；Windows 也可运行，但脚本示例按 `bash`
- 一个可直连的 OneBot V11 客户端

## 2. 安装

```bash
cd /path/to/taiko-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

## 3. 下载资源包

先访问：

- `https://viewer.sakura-bot.cn/api/taiko/manifest`

把 manifest 中的资源包下载并解压到项目根目录的 `assets/`：

- `core-assets`
- `dress-assets`
- `nameplate-assets`
- `cover-assets`
- `fumens-renamed`

解压完成后，项目根目录应至少存在：

- `assets/fonts`
- `assets/templates`
- `assets/icons`
- `assets/dress`
- `assets/name_plate`
- `assets/name_plate_dani`
- `assets/cover`
- `assets/fumens_renamed`

## 4. 本地配置

运行态私有数据统一落在 `storage/`，首次启动会自动创建。

常用配置文件：

- `storage/config/config.json`

最少需要填：

```json
{
  "cookie": "你的鼓众 cookie",
  "bemanicn": {
    "email": "",
    "password": ""
  }
}
```

`cookie` 用于 CN 成绩更新；`bemanicn` 仅在你要使用地图查询时需要。

## 5. 端口

默认端口：

- 本地数据 API：`127.0.0.1:37565`
- Core WS：`127.0.0.1:37563`
- Gateway WS：`0.0.0.0:37564`
- `nb run` 单进程：`0.0.0.0:37564`

可以在 `.env` 中改：

- `HOST`
- `PORT`
- `TAIKO_CORE_PORT`
- `TAIKO_GATEWAY_PORT`
- `TAIKO_LOCAL_DATA_API_PORT`

## 6. 启动方式

先启动本地数据 API：

```bash
source .venv/bin/activate
./scripts/start_local_data_api.sh
```

### 方式 A：直接运行 NoneBot

```bash
source .venv/bin/activate
nb run
```

### 方式 B：Core/Gateway 双进程

```bash
source .venv/bin/activate
./scripts/start_taiko_gateway_core.sh
```

## 7. 连接 OneBot 客户端

如果你使用网关模式，让 OneBot 客户端连：

- `ws://127.0.0.1:37564/onebot/v11/ws`

如果你直接 `nb run`，让客户端连：

- `ws://127.0.0.1:37564/onebot/v11/ws`

## 8. 首次启动行为

bot 在启动前会主动请求：

- `https://viewer.sakura-bot.cn/api/taiko/manifest`
- manifest 中声明的公共 JSON 数据

这些数据会缓存到项目根目录的 `songs/`。如果远端暂时不可用，但本地已有缓存，bot 会降级启动。

## 9. 本地数据 API

默认基址：

- `http://127.0.0.1:37565`

可用接口包括：

- `GET /health`
- `GET/PUT /v1/config`
- `GET/PUT /v1/userdata/{user_id}`
- `GET /v1/userdata/{user_id}/history`
- `GET/PUT /v1/runtime/multi-bind`
- `GET/PUT /v1/runtime/draw-guess`
- `POST /v1/public/sync`

## 10. 维护资源包

维护者更新资源包时可执行：

```bash
TAIKO_SOURCE_ROOT=/home/sigaer/taiko ./scripts/build_open_resource_archives.sh
```

默认输出目录：

- `/home/sigaer/taiko-open-resources`

viewer 侧 `api/taiko/resources/*` 会从该目录读取。
