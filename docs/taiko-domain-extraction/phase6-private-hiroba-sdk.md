# Phase 6 Hiroba 凭据 SDK

6.3e.8.4，客户端0.2.3。状态与绑定调用都在HTTP前要求有效Developer token；绑定保留原keyword参数，新增可选request_id，等待上限300秒。完整guarded validator的59项回归通过，含两个missing-token拒绝与一个nonce/timeout协议测试；固定Git安装Core0.1.2/Contract0.1.0不变。

跨账号状态读取需Viewer按token登记hiroba_credential_status与Source，绑定需hiroba_bind、明确Source及principals。普通token绑定依赖预先存在的完整自有Hiroba binding，不能把QQ字段、密码或登录成功当作资源授权。服务Source范围覆盖发现的全部目标卡片及QQ的已有全部成员；不同principal格式和大小写不合并。密码经HTTPS请求体和中心私有stdin，不进入worker argv。

服务端原卡片发现顺序、目标过滤、空结果和Fernet密文兼容。凭据、可选QQ metadata和最小回执在同一SQL事务提交；同凭据/授权/意图的已提交request_id重试跳过登录与重写，返回当前QQ结果，不覆盖后来选择。中心真实SQL、native worker、COMMIT前后进程退出和授权变化证据由Viewer的docs/taiko-domain-extraction/evidence/phase6-hiroba-credential-validation.json统一留档。配置方法见Viewer的docs/taiko-domain-extraction/source-service-operations.md。

本步仅发布客户端源码；运行中的中心R未复制或重启。旧provider磁盘/内存fallback与Hiroba状态缓存仍待permission-aware bounded cache迁移，不能据SDK要求token判定撤权已覆盖。所有Writer、完整Read Model、成本/恢复演练与统一发布/真实在线产品Gate仍属Phase6后续工作。
