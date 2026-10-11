# Phase 6 QQ 绑定 SDK

6.3e.8.3，客户端 0.2.2。三个中心绑定调用（lookup/upsert/current）在 HTTP 前要求 Developer token。两种 mutation 新增可选 request_id，原位置参数兼容；服务端同一凭据、完整授权和意图的重试返回当前选择，不重复写入或覆盖后续选择。

QQ 服务必须在 Viewer 按 token 登记 bind_read/bind_write/bind_current、显式 principals 及 Source 范围。身份为裸数字 QQ、onebot_v11:QQ 或 qq_official:openid；不同格式、大小写不自动合并。Source 范围包含 principal 的全部绑定和添加目标。普通 token 依赖当前 active、已验证 Viewer QQ 绑定，upsert 另要求自有同平台账号绑定。额度不是绑定授权，TAIKO_BOT_SERVICE_TOKEN 继续用于独立手动账号协议。

完整 guarded validator 通过 56 项（本步新增三个 missing-token 拒绝及一个 request_id/调用兼容测试）。沿用固定 Git 安装 Core 0.1.2 / Contract 0.1.0，验证不读生产个人 storage、不发送 HTTP；运行时固定依赖不变。真实 Cookie/token/服务 policy、SQL 原子事务与进程退出证据由 Viewer 的 docs/taiko-domain-extraction/evidence/phase6-bot-binding-validation.json 统一留档。授权登记详见 Viewer 的 docs/taiko-domain-extraction/source-service-operations.md。

本步发布客户端源码；本仓库暂无运行中的业务进程。Hiroba credential status/bind 和 permission-aware bounded cache 尚待迁移；旧 provider fallback/缓存不视为完成撤权验证。中心 Source/R 未同步或重启，Viewer 最终标准部署与线上产品验收仍属完整 Phase 6 Gate。
