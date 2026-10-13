# Phase 2F-D0.6 — PreparedPrivateInput Boundary Prototype

日期：2026-10-13。状态：**PHASE_2F_D0_6_PREPARED_INPUT_VALIDATED**。

基于 D0.5 `8299f54` 与已安装的 Application **0.6.0**。独立工作树：
`/var/tmp/taiko-phase2fd06-20261013/application`；分支：`prototype/prepared-private-input`。
本轮仅验证合成 fixture 的 Host Provider → PreparedPrivateInput → 现有 execute_score 边界。
没有迁移 tinfo matcher，没有适配生产 renderer，没有修改 Writer、PublicationStore、storage、数据库或生产，没有新建服务/API。

## 实现

实验代码位于 [prepared_private_input](../packages/taiko-application/experiments/prepared_private_input/)，不在 setuptools 的 `src` 发行目录中。不新建发行包，不改变 Application 0.6.0、任何依赖或版本声明。

- `dto.py`：内部 `PreparedPrivateInput` 包含 `authorized_target`、`current`、可空 `history` 和 `provenance`。嵌套 JSON 数据复制为 MappingProxyType/tuple，隔离原始可变输入；拒绝 Path、函数、任意 handle/object、bytes 等非数据值。DTO 无 writer、store handle、filesystem path 或 resolver callback 字段。
- `AuthorizedTarget`：记录 fixture actor/principal、用户 ID、有序成员、profile 来源及授权观察标签。标签只是测试数据，不是授予真实访问权的令牌。
- `Provenance`：记录 fixture representation、current/history view、成员、profile、rule 标识；拒绝目标不一致或跨 view 拼接。使用合成 view 标识，不冒充真实 dependency hash、publication 或远程 sourceView。
- `host_fixture.py`：内存中的 normal、u0、缺历史、成员变更、profile 变更场景；提供 preparation 和发送前复核的模拟边界。u0 current 是预制的真实结构合成 payload，不调用 merged_bind、不重写合并规则或物化。
- `application_adapter.py`：从 DTO 构造现有 CommandContext/ScorePorts，调用已安装的 `execute_score`；图片 Port 的闭包仅持有 prepared 数据及测试故障参数，不持有 Host Provider。user_id 只作目标一致性检查，不用于再次加载数据。
- `render_fixture.py`：160×96 合成图，颜色随 profile、图形随成绩和 stage_cnt 改变。用真实 Pillow 编码 PNG/JPEG。它不是生产 tinfo 版式或新产品 renderer；作用是使错误输入无法靠固定图片通过 parity。

Application 不进行授权决策。fixture 在 preparation 前验证，发送前另行比较目标，包括有序成员及 profile；已准备数据保持不变，不意味着权限永远有效。调用者可以构造实验 DTO，因此它不构成安全沙箱或可信授权边界本身。

## 旧 tinfo 对比方法

沿用既有 `tests/commands/provenance.json` 的冻结中心 tinfo 源文件：
SHA256 `fd4b1c395fbcfc4941e8a14343e3ca9d95d0ddd31c59e2fcfe3fd68b2683e41e`。
抽取完整、未修改的 `music_info_handle` 函数体及 fuzzy/JPEG 辅助函数，移除注册装饰器，保留实际分支与错误处理。抽取文件的 hash 和函数列表随 `provenance.json` 保存，不 import Sakura 或启动 NoneBot。

旧路径在图片生成时通过 fixture user_id 读取数据；新路径先由 Host Provider 准备 DTO，再执行现有 `execute_score`。两边使用相同的合成 catalog 和数据敏感图片 fixture；旧函数使用冻结 JPEG 转换，新适配器使用实验内存转换。只替换外部数据源/图片 fixture/发送截获，不替换旧 tinfo 的判断、分支或异常映射。

比较内容：文字全文、direct/reply、fuzzy prefix、JPEG 字节 SHA256、像素 SHA256、尺寸和 mode；应向外传播的错误比较异常类型与消息。唯一归一化是 Pillow `UnidentifiedImageError` 消息内 BytesIO 对象的进程内地址，其他文字不归一化。正常用例必须成功，不以两边同时报错充当通过。

## 验收

通过既有 `scripts/memory/run_qa.sh` 执行，使用 D0 的独立虚拟环境中已安装的 Application 0.6.0 / Pillow 11.3.0；未安装到生产。最终 **82/82 PASS**，pytest 用时 0.37 秒（不包含整个 runner 的启动和审计耗时）。

| 范围 | 结果 |
| --- | --- |
| 五种输入 × 九种 tinfo 分支 | 45/45：单曲、多结果、无结果、fuzzy 接受/拒绝、无效 ID、缺曲目记录、格式错误、非法上游返回 |
| 五种输入 × 四种故障 | 20/20：FileNotFoundError、RuntimeError、TypeError 的既有文字映射及 JPEG 解码错误传播 |
| DTO/Host 边界 | 17/17：不可变性、输入所有权、能力对象拒绝、provenance/current-history 不匹配、缺历史、撤权、准备后禁止重入 Host、成员/profile 改变 |
| 新进程运行检查 | 8 次 prepared 执行通过；禁止依赖导入尝试 0，执行期文件/目录/网络/SQL/子进程 IO 尝试 0 |

65 个 parity 用例中，15 个返回图片，40 个返回文字，10 个按预期传播异常。成员变化或 profile 变化后重新准备，新的图片 hash 必须变化并仍等于旧路径；旧 DTO 不变，但 Host 的交付复核拒绝它。另专门保持同一 user_id 和同一授权观察标签，只改变成员顺序或 profile，验证仍会拒绝；不能仅靠标签变化碰巧通过。

首次测试出现五个 JPEG 错误消息地址差异：两边类型及消息模板一致，但 BytesIO 的内存地址不同。随后只归一化这一地址并重跑；没有修改 execute_score 或冻结处理逻辑。

## 边界审计

`audit_imports.py` 从实验适配器及 `taiko_application.commands.score` 遍历可达的项目自有 imports，包括父包 `__init__`。共 13 个模块，未出现 taiko_store、merged_bind、userdata loader、Writer；实验适配器也不可导入 host_fixture 或 oracle。包含一个经中间模块转入 taiko_store 的负对照，必须被拒绝。

`runtime_audit.py` 在新进程中先安装禁止依赖的 import guard，再导入适配器。公开 Pillow codecs 在禁止执行期 IO 前初始化；随后执行 DTO 构造、文字和图片分支，审计所有上述 IO 尝试，即便异常被捕获也会导致验收失败。报告保留被审计模块及源码 hash。

本处“Application import graph”指 **本次调用的传递可达导入图**，不是声称删除 Application 0.6.0 已有的 `taiko_application.merged_bind` 文件。该模块继续属于 D0，但不进入此实验图。审计既有 commands 包初始化间接导入的其他 command 模块；并未执行 B30/progress/recommendation。

已安装 `execute_score` 文件与基线源码字节一致。全部既有 tracked 实现保持不变；九个公开入口和 35 处客户端发送前检查没有改动。本轮不重做生产图片、两端真实授权或真实 publication 的验收，不把合成 Host 复核当作中心撤权安全证明。

## 证据与复现

- [完整验收 JSON](../packages/taiko-application/experiments/prepared_private_input/acceptance.json)：65 个逐项结果、图片 hash、导入图与运行检查。
- [冻结参考 provenance](../packages/taiko-application/experiments/prepared_private_input/provenance.json)。
- 临时证据：`/var/tmp/taiko-phase2fd06-20261013/evidence/validation.json`。

从 Viewer 仓库使用既有隔离 runner（Python 环境需装 Application 0.6.0、Pillow 11.3.0、pytest）：

```sh
bash scripts/memory/run_qa.sh /usr/bin/env PYTHONDONTWRITEBYTECODE=1 \
  /var/tmp/taiko-phase2fd0-20261013/env/bin/python \
  /var/tmp/taiko-phase2fd06-20261013/application/packages/taiko-application/experiments/prepared_private_input/run_validation.py \
  --output /var/tmp/taiko-phase2fd06-20261013/evidence
```

此原型验证数据边界可行，不意味着真实 Host Provider 已实现，也不意味着 tinfo matcher、生产 renderer、u0 Writer 或 D1 已可直接迁移。没有合并 main、部署、重启或进入后续阶段。完成后停止。
