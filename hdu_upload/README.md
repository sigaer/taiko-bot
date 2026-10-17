# HDU 视频素材上传页

静态前端通过短时签名 URL 将文件分片直传至 `sigaer` OSS 的 `video_4/` 前缀。长期 OSS 凭据只由本机签名服务读取，不会进入浏览器资源。

## 本地验证

```bash
python3 -m unittest hdu_upload.tests.test_server
python -I -m hypercorn --bind 127.0.0.1:3104 hdu_upload.wsgi:app
```

静态文件由 Nginx 提供，`/api/` 反向代理到 `127.0.0.1:3104`。

生产单元位于 `deploy/hdu-uploader.service`，随独立 Taiko 发行环境部署。静态代码可部署到既有 Nginx 根；`miku.png` 和 `favicon.ico` 由私有资源包提供。
