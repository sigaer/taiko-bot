# taiko-bot

`taiko-bot` 是从原私有运行栈中抽离出的独立 NoneBot 项目。这个仓库只包含 bot 执行逻辑，不包含私有 cookie、BEMANICN 账号、权威成绩文件或手工维护的资源包。

## 1. 环境要求

- Python `3.11` 推荐
- Linux/macOS 推荐，Windows 也可运行
- 一个可直连的 OneBot V11 客户端
- 可访问 `https://viewer.sakura-bot.cn`

## 2. 安装 Python

如果本机没有 Python 3.11，请先安装：

- Windows：从 `https://www.python.org/downloads/` 安装 Python 3.11，并勾选 `Add python.exe to PATH`
- Ubuntu/Debian：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

## 3. 安装项目

```bash
cd /path/to/taiko-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

## 4. 配置 `.env`

必须至少配置这些项目：

```env
HOST=0.0.0.0
PORT=37564
TAIKO_LOCAL_DATA_API_PORT=37565
TAIKO_VIEWER_BASE_URL=https://viewer.sakura-bot.cn
TAIKO_VIEWER_DEVELOPER_TOKEN=你的开发者token
```

说明：

- `TAIKO_VIEWER_DEVELOPER_TOKEN` 是开源 bot 访问中心受限接口的唯一默认凭据
- 不再需要根目录 `config.json`
- 不再需要 `storage/config/config.json`
- 不再需要本地鼓众 cookie
- 不再需要本地 `bemanicn` 账号

可选端口：

- `HOST` / `PORT`：`nb run` 对外监听地址
- `TAIKO_CORE_PORT`：Core 模式端口
- `TAIKO_GATEWAY_PORT`：Gateway 模式端口
- `TAIKO_LOCAL_DATA_API_PORT`：本地 FastAPI 数据服务端口
- `HIROBA_PROXY`：仅当你的 Hiroba 登录必须经过指定代理时再填写；`绑定hiroba` 不会继承宿主机通用 `HTTP(S)_PROXY`

## 5. 首次启动会自动完成什么

启动 `nb run` 前后，bot 会自动执行：

1. 拉取公共 JSON 数据到 `songs/`
2. 检查 `assets/.bundle.sha256`
3. 如本地资源缺失或版本变化，自动从 `viewer` 下载单一总资源包并解压到 `assets/`
4. 成绩相关读取按需从中心拉取并缓存到 `storage/cache/userdata/`
5. 地图查询按需从 `viewer` 同步本机缓存快照到 `storage/data/arcade_map_cache/`

注意：

- 用户不需要手动下载资源包
- 如果本地完全没有资源，且资源包下载失败，启动会直接失败
- 如果本地已有资源，但资源更新失败，bot 会告警后继续使用旧资源

## 6. 启动本地数据 API

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

其中 `userdata` 仅是本地读取缓存，不是权威成绩落点。

## 7. 启动 NoneBot

### 方式 A：单进程

```bash
source .venv/bin/activate
nb run
```

### 方式 B：Core / Gateway 双进程

```bash
source .venv/bin/activate
./scripts/start_taiko_gateway_core.sh
```

## 8. 连接客户端

如果使用默认 `nb run`：

- `ws://127.0.0.1:37564/onebot/v11/ws`

如果使用网关模式：

- `ws://127.0.0.1:37564/onebot/v11/ws`

## 9. 成绩更新与读取规则

- `taikoupdate` / `更新广场`：请求中心服务更新，权威写入只发生在当前中心设备
- `更新hiroba`：请求中心服务执行 Hiroba 同步，结果也只写入中心设备
- 自部署 bot 本地只保留读取缓存，不作为权威成绩存储
- `b30`、进度图、查分、总结等读取都会优先刷新中心缓存后再渲染

## 10. 地图查询规则

- `xx哪有鼓` 不再登录 BEMANICN
- 本地只查询从 `viewer` 同步下来的地图快照缓存
- 首次无缓存时会自动尝试同步

## 11. 维护资源包

维护者更新中心资源包时：

```bash
TAIKO_SOURCE_ROOT=/home/sigaer/taiko ./scripts/build_open_resource_archives.sh
```

默认输出：

- `/home/sigaer/taiko-open-resources/taiko-bot-assets.zip`

viewer 对外下载入口：

- `https://viewer.sakura-bot.cn/api/taiko/assets/latest`
