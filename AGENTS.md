# taiko-bot Notes

## Scope

- 这个仓库是 `taiko-bot` 的唯一开发源头。
- 后续 taiko bot 逻辑更新先改这里，不再先改旧 `/home/sigaer/taiko` 运行树。

## Data Contract

- 公共 JSON 数据通过 `https://viewer.sakura-bot.cn/api/taiko/*` 获取。
- 资源包通过 viewer 域名的 `api/taiko/resources/*` 提供。
- 如果改动了数据集名称、manifest 结构、资源包名称或路径，必须同步修改：
  - `taiko-bot`
  - `/home/sigaer/taiko/taiko-forum/taiko_viewer`

## Runtime Storage

- 私有运行态数据统一落在 `storage/`。
- 不要把 `songs/`、`assets/`、`storage/`、用户文件、cookie、导出的 JSON 提交进仓库。

## Release Sync

- 资源包更新后，先重新生成压缩包，再验证 viewer 的 `api/taiko/manifest` 和 `api/taiko/resources/*`。
- viewer 侧 API/资源协议变更后，再更新 README 和 `.env.example`。
