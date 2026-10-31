# taiko-bot

《太鼓达人》QQ Bot，支持 OneBot V11 和 QQ 官方机器人。曲库、素材和成绩通过 `https://viewer.sakura-bot.cn` 获取。

常用功能：歌曲与别名查询、查配置、查分、B30、推荐、进度与趋势、我的小咚、词云、机厅地图、猜歌，以及账号绑定、切换和成绩同步。

## 1. 准备

- Python **3.11**、Git，Windows / Linux / macOS 均可。
- 已能登录的 OneBot V11 客户端，或 QQ 官方机器人应用凭据。
- 可访问 PyPI 和 `https://viewer.sakura-bot.cn`。
- 已获批的 **Developer token**，用于读取全部用户成绩及调用 Bot 绑定、同步接口；仍受每日额度限制。

常规部署无需自建 Viewer、MySQL 或 Redis 服务。

## 2. 安装

### Windows PowerShell

```powershell
git clone https://github.com/sigaer/taiko-bot.git
cd taiko-bot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### Linux / macOS

```bash
git clone https://github.com/sigaer/taiko-bot.git
cd taiko-bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
cp .env.example .env
```

以下命令均在 `taiko-bot` 目录、已激活的虚拟环境内执行。

## 3. 配置

编辑 `.env`，填写自己的 Developer token：

```env
HOST=0.0.0.0
PORT=37564
TAIKO_SONG_PROFILE=client
TAIKO_VIEWER_BASE_URL=https://viewer.sakura-bot.cn
TAIKO_VIEWER_DEVELOPER_TOKEN=你的DeveloperToken
```

### OneBot V11

在 OneBot 客户端配置反向 WebSocket：

```text
ws://127.0.0.1:37564/onebot/v11/ws
```

如果 OneBot 与 Bot 不在同一台设备，把 `127.0.0.1` 改为 Bot 的可达地址，并放行配置的端口。

### QQ 官方机器人（可选）

在 `.env` 中增加：

```env
QQ_IS_SANDBOX=false
QQ_BOTS=[{"id":"你的AppID","token":"你的Token","secret":"你的Secret","use_websocket":true,"intent":{"c2c_group_at_messages":true,"at_messages":false}}]
```

测试应用可改为 `QQ_IS_SANDBOX=true`。接收事件需在 QQ 开放平台启用相应权限。

若使用 Markdown 图片消息，还需将本机 `storage/output/qq_markdown_cache/` 通过自己的 HTTPS 静态站点公开，并设置对应地址：

```env
QQ_MARKDOWN_IMAGE_BASE_URL=https://你的域名/qqbot-cache/taiko
```

## 4. 启动与验证

```bash
python bot.py
```

首次启动会拉取公共曲库，并在后台下载、解压素材到 `assets/`；较慢网络下可能需要约 15 分钟。素材未就绪时图片命令会提示稍后再试。

确认 OneBot 已连接，发送：

- `青春达人`：检查基本收发。
- `xx是什么歌`：查询歌曲，将 `xx` 换为曲名或别名。
- `绑定 鼓众广场ID`：按 Bot 提示完成账号验证。
- `b30`：查询当前账号成绩图。
- `taikoupdate`：更新当前华立账号成绩。
- `更新hiroba`：同步已配置 Hiroba 凭据的账号。
- `u1` / `u2`：切换已绑定账号。

停止时按 `Ctrl+C`；下次进入目录、激活虚拟环境后再次执行 `python bot.py`。

## 5. 常见问题

- **安装失败**：确认 Python 为 3.11，并从仓库根目录执行 `python -m pip install -r requirements.txt`。
- **Bot 不回复**：检查 OneBot 反向 WebSocket 地址、连接日志和端口；若群功能曾被关闭，由群管理员发送 `开启taiko功能`。
- **401 / 403**：核对 `.env` 中的 Developer token 是否有效、已获批或已撤销；修改后重启 Bot。
- **429**：开发者当日额度已用尽，等待额度恢复。
- **图片提示资源未就绪**：等待后台下载完成，并检查 Viewer 网络连通性及磁盘空间。
- **手动成绩账号**：创建、认领和修改还需维护者提供的 `TAIKO_BOT_SERVICE_TOKEN`；可留空，不影响上述常用功能。

升级时停止 Bot，执行 `git pull` 和 `python -m pip install -r requirements.txt`，再启动。保留自己的 `.env`、`storage/`、`songs/` 和 `assets/`。

许可：[GPL-2.0-only](LICENSE)。
