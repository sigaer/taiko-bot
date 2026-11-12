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

## 中心曲库维护

每日歌曲任务将 OurTaiko 与 TaikoWiki 取并集，合入中心 `songs/song_data.json`，Bot 和 Viewer 共同读取。主要来源是 OurTaiko 的 `/api/v1/game/catalog`，加上 `/api/v1/charts?files=no` 的无文件条目；合并总数必须与数据库总数一致，否则回退完整分页。TaikoWiki 作为歌曲和元数据补充源，故障时使用最近有效缓存，不阻断 OurTaiko 更新。已有字段保留，仅补充缺失字段、`official_id`、`ourtaiko_ids` 和 ESE 路径。

虹 ID 直接使用 `id`，无虹 ID 的曲目沿用 `100000` 起的其他平台编号。平台转入街机、虹 ID 变更或重复曲目按上游持久 ID、完整 TJA 路径、唯一同名同难度证据归并。旧 ID 统一记录在新曲目的 `legacy_ids`；公共引用、旧歌曲链接与历史成绩读取使用这一份映射。原始成绩、历史字节及发布哈希保持不变，重复成绩保留分数最高的实际记录，不叠加游玩次数。官方 ID 仅供记录。

分类沿用 `shelf_status`：0 国行上架、1 未上架、2 其他平台。虹 ID 曲目按最新成功华立列表区分上架、未上架；无虹 ID 的曲目归入其他平台。TJA、音频或某一谱面缺失不阻塞其余曲目。

维护者可用 `python -I -m taiko_bot.offline.catalog_import --root /path/to/staging` 预览；`--cached` 使用完整抓取缓存，`--write` 原子发布曲库并备份旧文件。暂存目录需准备现有 `songs/song_data.json`、`song_id2tjapath.json`。分页不完整时保留上次完整缓存。

`python -I -m taiko_bot.offline.catalog_constants --root /path/to/staging` 使用 Viewer 已准备的固定版本 `.tja-runtime/calculate.py`，只补 CSV 中缺少的单人谱定数，保存 `catalog_constants.json` 的物量/星级校验证据。`--limit N` 可分批续算。既有定数行保持原值；双打、物量不一致和解析失败的谱面留空并记入报告。每日任务也会增量补算，可通过 `TAIKO_CONSTANTS_CALCULATOR` 指定同一计算器路径。

本地 ESE 找不到的谱面，从对应 OurTaiko 持久 ID 的 `/resources` 接口取得下载清单，流式校验 SHA-256、大小和课程星级后写入 `assets/catalog_sources/ourtaiko`。这些曲目以 `resource_source: ourtaiko` 标明路径根目录；不改动 ESE 仓库，也不替换已有可用文件。TJA 与 WAVE 音频一起校验，Viewer 下载和定数计算使用同一资源解析规则。

`python -I -m taiko_bot.offline.catalog_images` 按固定版本 [WHMHammer/tja-tools](https://github.com/WHMHammer/tja-tools) 生成缺失的 PNG；每日更新也执行增量补图。标题优先使用曲库中文名，无中文名时使用原名，不附加水印，不修改源 TJA。生成前校验难度、单双打和已有物量，P1/P2 分别输出，保留已有图片。单浏览器、单页面、逐图处理，图像尺寸、单图时长和文件大小有上限；异常谱面记录在 `logs/catalog_image_report.json`。维护回填通过现有内存隔离 wrapper 分批执行，资源总包更新后再供客户端同步；客户端按流计算大资源包哈希。定数计算继续使用原固定版本计算器。

补算同时只填充已验证单人谱的缺失物量，适用于既有与新增曲目，已有物量保留，供 Viewer 的同谱校验使用。

每日补图后自动执行标准资源包脚本的 `fumens` 范围，更新谱面包和总包；失败会保留重试标记。维护时可用 `scripts/build_open_resource_archives.sh fumens` 单独发布图片。开发验证和构建仍须使用现有内存隔离 wrapper，业务数据及生成结果不提交到源码仓库。

许可：[GPL-2.0-only](LICENSE)。
