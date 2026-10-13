# Phase 2F-D1 — tinfo ownership boundary

状态：**PHASE_2F_D1_BLOCKED**。日期：2026-10-13。

基线 Taiko `14fc23a428be5b627af71d39f359aae1c755f171`、Sakura `38826aab306f7e51290f71682fd915b2537d1276`；两个独立分支均为 `integration/tinfo-ownership-cutover`。本次仅提交阻断证据，没有迁移运行实现。

## 确认的阻断

中心虚拟账号 u0 的真实源码调用链：

`plugins/taiko.py:music_info_handle` → `_resolve_read_bind_target_safe` → `_resolve_read_bind_target` → `plugins/utils/merged_bind.py:materialize_merged_bind_userdata` → `taiko_store/merged_materialization.py:materialize`。

`materialize` 在第 81 行取得 `store.exclusive()`；第 105/111/114 行可 stage current/history；第 115 行 `store.publish(...)` 发布。已有依赖一致时可以直接返回，但首次生成或成员 publication 改变时会走持久化路径，不能称作纯只读 Provider。第 37 行还直接 import `plugins.utils.merged_bind` 的合并内核和模型。

完整保留虚拟账号行为，同时让外部插件拥有只读 Provider 且不反向依赖 Sakura 专用 utils，不能通过原样移动或调用这条链实现。以不透明 callback 隐藏 materialize 仍然有写入；仅读取现有虚拟文件无法证明新鲜性和原错误语义；改成请求内重算或改物化/历史协议超出本轮范围；关闭 u0 则违反保留虚拟账号要求。因此遵照本轮第 6 条停止，不建立新的基础设施或写入桥。

此结论针对冻结中心源码的 u0 路径，不表示所有实账号查询都会写入，也不宣称生产运行目录采用相同存储实现。未读取私人 userdata 或调用物化函数。客户端本身不是这条中心物化链的证据来源；没有借中心阻断启动客户端单端迁移。

## 完成范围与验收

- 已从实际最新 main 创建两仓隔离分支，基线与要求一致。
- 静态 AST 核对完整调用链、行号、文件 SHA256；无项目 import、SQL、网络业务调用或用户数据读取。检查通过 memory/run_qa.sh 执行。
- 源码移除清单：**空**。两个宿主 `music_info` matcher/handler 保留，外部玩家插件未建立；九个公共入口没有变更。
- 客户端 35 处发送前授权检查原样保留，其中 tinfo 8 个出口调用；没有复制或新增复核。
- 双平台图片/文字 parity、实时撤权时序、外部 tinfo 唯一注册验收均为 **NOT_RUN**，没有实现候选，不能宣称通过，也不据此断言中心现有撤权安全。
- Application 0.5.0、中心 Core 0.1.1、客户端 Core 0.1.2、Contract 0.1.0 和全部包声明保持不变。

剩余依赖由既有中心绑定/合并账号存储维护边界负责。后续若继续，必须先单独明确如何提供保持 u0 语义的只读授权/成绩输入边界；本轮不设计或实现该方案，不以现有成绩缓存证明授权仍有效。

仅文档和匿名源码证据提交；未修改 storage、Writer、SQL、sync、daily/history、生产 P0、生产运行目录或其他命令。未合并 main、部署、重启或进入 Phase 6。完成后停止。
