# OurTaiko 曲绘上传

维护脚本：`scripts/upload_ourtaiko_covers.py`，使用 Python 3.11+、requests、Pillow。
独立运行，无需部署或重启 Bot。

只按 `ourtaiko_ids`、虹版编号和唯一官方编号匹配。冲突、无本地曲绘、损坏图片会留在计划中，绝不按相似曲名猜测。支持 Database SQL 导出的 snake_case 字段及 API camelCase 字段。
优先读取当前本地编号的曲绘；若不存在，则查找曲库明确记录的 `legacy_ids` 下的图片，原地读取，不移动或复制业务素材。

先生成计划（默认不会登录或上传）：

```bash
cd /home/sigaer/taiko-bot
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_dev.sh \
  /opt/taiko-bot/current/bin/python -I scripts/upload_ourtaiko_covers.py \
  --charts '/home/sigaer/taiko/charts 2026-11-12 15-47-29.json'
```

通过隔离包装器实际上传时，追加 `--apply --credentials-file /run/私有文件.json`。
文件须由当前用户拥有且权限为 0600，包含 `username`、`password`。密码不能写进命令行、仓库、日志；任务完成后删除该临时文件。
在有终端的环境直接使用脚本时，也支持 `--apply --username sigaer` 隐藏输入密码；非交互环境必须使用私有凭据文件。
可以追加 `--proxy http://127.0.0.1:端口`。不传时遵循当前环境的代理设置。

默认结果目录：`/home/sigaer/taiko/storage/ourtaiko-cover-upload/`（可用 `--state-dir` 指定）。

- `plan.json`：完整匹配计划及跳过原因。
- `uploads.jsonl`：每次上传结果、本地源文件 SHA256、远端曲绘 SHA256。
- `summary.json`：本轮结果与计数。

已有曲绘也会替换。每张上传后读取详情核对 `coverHash`，每轮首张还下载验证实际图片哈希；有 TJA 的曲目，其 `PREIMAGE` 由服务器同步更新。
若本地扩展名与实际图片格式不一致，上传表单的文件名按图片实际格式设置，保留本地文件和原始图片字节。
重新执行相同命令会核对历史成功记录和当前远端哈希，自动续传；`--limit 1` 可先做单张验证。默认写请求至少间隔 1.7 秒，429/服务故障有界重试，认证或权限错误立即停止。
补传指定曲目可重复使用 `--local-id 本地编号`，仅处理这些曲目。

合成数据测试（不访问网络及业务数据）：

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/current/bin/python -I tests/test_ourtaiko_cover_upload.py
```
