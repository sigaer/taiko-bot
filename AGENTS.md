# taiko-bot Notes

## Scope

- 这个仓库是 `taiko-bot` 的唯一开发源头。
- 后续 taiko bot 逻辑更新先改这里，不再先改旧 `/home/sigaer/taiko` 运行树。

## Data Contract

- 公共 JSON 数据通过 `https://viewer.sakura-bot.cn/api/taiko/*` 获取。
- 资源包通过 viewer 域名的 `api/taiko/assets/latest` 提供单一总包。
- 成绩更新与 Hiroba 同步统一走 viewer 的中心代理接口，权威写入只发生在当前中心设备。
- 自部署 bot 本地只保留读取缓存，不把本地缓存当作权威 `userdata`。
- 如果改动了数据集名称、manifest 结构、资源总包名称或中心代理路径，必须同步修改：
  - `taiko-bot`
  - `/home/sigaer/taiko/taiko-forum/taiko_viewer`

## Runtime Storage

- 私有运行态数据统一落在 `storage/`。
- 不要把 `songs/`、`assets/`、`storage/`、用户文件、cookie、导出的 JSON 提交进仓库。

## Release Sync

- 资源包更新后，先重新生成总压缩包，再验证 viewer 的 `api/taiko/manifest`、`api/taiko/assets/latest` 与相关代理接口。
- viewer 侧 API/资源协议变更后，再更新 README 和 `.env.example`。
