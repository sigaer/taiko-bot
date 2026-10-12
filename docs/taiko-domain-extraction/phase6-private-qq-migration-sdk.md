# Phase 6 QQ 验证迁移 SDK

6.3e.8.6g，客户端0.2.7。原QQ私聊旧bot申请“迁移验证码”，目标私聊输入“绑定QQ QQ号 验证码”。SDK走private `/api/taiko/proxy/bind/qq-code`与`qq-migrate`；中心Developer token另需bind_migrate、canonical principal和原绑定/目标已有全部Source。普通token只能用当前active、已验证Viewer QQ owner访问对应OneBot principal；official身份需要明确service subject，不能根据输入QQ号推断所属。

本地SQLite/JSON QQ迁移读取和逐次upsert已移除，无local authority fallback。中心私有任务调用同一原生SQL事务，凭据转移、绑定、当前选择和code消费一个COMMIT。源记录/顺序、canonical优先/bare fallback、SQL真实current、目标visibility（含0）保持；origin manual仍用专用认领，target manual保留。码仅存hash、十分钟TTL/一分钟申请间隔。申请一次请求；消费code同target最多两次网络/503 retry，self migration一次。返回当前target绑定，重试不重置选择、复活解绑或重复首次自动更新。摘要/自动更新出错不把已经提交的绑定误报回滚。

共享transport256KiB streaming、90s分块检查/10s socket及无redirect/token必需不变；不声称严格90s进程期限。SDK验证principal/QQ/code/TTL以及effect类型和bound DTO，错误固定文案，不显示SQL/路径/token diagnostics。码仅发私聊，不记入文件/audit；命令/按钮/提示一致，保留原裸QQ输入形式但不同身份必须提供code。

223 guarded client（195既有+28新）、241 Source（231既有+10 private frame）、TS、最终23真实_test SQL/HTTP与10纯worker transport全PASS。SDK/actual command AST到owned H3/private CLI/MySQL；cookie/服务subject/scope/全部Source、late撤权/回滚/ACK、四个真实COMMIT退出及独立SIGALRM、credential-bind-code原子、later selection/解绑重试和captured runtime。初轮未变160实际SQL+1策略另记，合计183实际SQL、11纯检查分轮。无真实上游、完整Bot/Nuxt启动、百万性能或线上验收。61.846s/250ms sample445947904bytes/child362448KiB/high-max-OOM0，wrapper25873和systemd unit1791772648-2099982成功/无残留；三类fixture/module-registration失败保留在中央证据。

本步源码提交/push。客户端尚无运行业务进程，中心Viewer0.82协议和生产显式grant未激活，线上仍0.81.11，R未复制/重启；独立push不代表可单独连接旧中心运行。Core0.1.2完整Git pin不变。回退B6ade2e1/0.2.6、配套回退Sourcef04b320与Viewer准备afb3b0d；激活后不得重新开放未验证的QQ复制路径。中央证据为Viewer `docs/taiko-domain-extraction/evidence/phase6-client-qq-migration-validation.json`。Native authority/Gate6仍IN_PROGRESS，剩余Native/private reader/update、全部Writer/P1a、Read Model/成本/ops/统一上线继续执行。
