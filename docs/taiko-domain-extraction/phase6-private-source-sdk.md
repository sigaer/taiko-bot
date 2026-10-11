# Phase 6 私有成绩 SDK

版本0.2.1。原四项私有成绩调用（current/history/Wahlap更新/Hiroba同步）现在在发起HTTP前要求Developer token，Hiroba同步等待上限900秒。公开数据与其他代理用途保留；quota不代表Source授权，跨账号服务按token登记明确Source/scopes。协议与登记入口见Viewer的docs/taiko-domain-extraction/source-service-operations.md。

完整客户端guarded validator通过52项（新增4个missing-token拒绝），使用Phase4固定Git安装Core0.1.2/Contract0.1.0，不读取生产个人storage、不发送HTTP。完整中心SQL/Source/worker/renderer证据见Viewer的phase6-source-proxy-validation.json，客户端受测文件SHA同步归档。QA驱动初次误用系统Core0.1.1在收集时停止，纠正后通过；未改变系统或生产中心的依赖。

本步为SDK源码发布；本仓库没有运行中的业务进程，因此无需重启。Hiroba credential/bind、QQ bind私有协议和permission-aware bounded cache继续Phase6后续步骤；旧provider缓存仍待收敛，不把SDK token开关当作完整缓存撤权验证。Viewer/R最终激活尚待完整Phase6 Gate，不提前宣称已部署。
