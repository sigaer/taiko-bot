# Client send authorization hotfix

状态：**CLIENT_SEND_AUTH_HOTFIX_READY**。基于 main `fa0983dcc56ca109555a33d90aac0fecca6bdf0d`（0.2.7），独立候选版本 **0.2.8**；参考 Phase 2E-R `44aaf656` 的授权复核，不合入 Application 抽取或资源根修复。

B30、tinfo、私有进度、私有推荐取到账号后的 35 个终止发送出口，均在调用原发送函数前重新执行既有 `_resolve_read_bind_target_safe`。复核身份绑定、账号、来源、虚拟账号属性；失败、撤销、超时、身份变化或异常均返回“授权已失效，请重新查询。”，不发送旧结果。覆盖图片、推荐私人文字结果以及错误出口。原命令计算、文字、PNG/JPEG、前缀和发送方式均保留，公开歌曲/定数查询不增加授权检查。

复核沿用现有中心 binding 查询和实时成绩读取；成绩缓存不是授权证明。没有新 API、缓存或服务器权限机制；复核与跨平台网络发送之间不构成原子 lease。

## 验证

- 空隔离 venv 完整依赖安装及 `pip check` 通过。Core **0.1.2**、Python Contract **0.1.0** 不变，**未安装或引入 taiko-application**，没有使用 `--no-deps`。
- main 冻结命令在“真实绘图后撤权”的红灯测试中仍发送 B30 图片；候选修复通过。
- B30/tinfo 使用既有公开曲库、30 条合成成绩、固定资源，执行真实 Provider、Core、renderer、JPEG 和 OneBot 消息。与 main 比较 PNG hash、pixel hash、dimensions、mode 和最终消息载荷，两条均一致。
- 复用 **10/10** 真实链路时序：两条命令 × binding 403、成绩 403、超时、身份切换、非法身份。全部拒绝发送旧图片；成绩 403 还验证 current 缓存项已失效。
- **54/54** 真实 NoneBot matcher/rule/handler 分派通过。包含 **24** 个正常/空/非法输入/既有错误/初始拒绝用例，与冻结 main 响应一致；另有 **30** 个发送前拒绝用例，覆盖四类私有命令及推荐私人文字，含账号、来源和虚拟身份变化。框架异常被捕获，真实网络/SQL 连接被禁止。
- AST 审计：移除新增复核语句及包装后，整个 `plugins/taiko.py` 与 main AST 完全相同；依赖列表完全相同；`plugins/utils` 和 `taiko_bot` 无变化。wheel、已安装代码与候选源文件字节一致。

正常 B30/tinfo 各增加 **1 次 binding 查询 + 1 次 current 实时读取**，原 Provider 顺序作为前缀不变，每次结果只复核一次。MockTransport 下复核分别约 **1.99 ms / 1.53 ms**；这仅是本地模拟测量，不代表线上 RTT/P95。线上多两次中心往返，沿用现有超时和错误处理，没有扩大为性能重构。

测试只在临时隔离目录执行，全部通过已有 `scripts/memory/run_qa.sh`。未运行整个 Application 回归矩阵。旧 renderer 的资源路径仅在测试输入层指向固定资源，未回移 Phase 2E-R 的资源定位修复。没有修改 storage、Writer、SQL、sync、Core 公式、Viewer 或生产目录，没有合并 main、部署或重启。

## 复现与证据

[精简结果及图片 hash](../tests/send_auth/result.json)、[测试代码与输入 hash](../tests/send_auth/)。完整本地证据：`/var/tmp/taiko-client-send-auth-evidence/`，包括 install/check、normal/reference、五组撤权结果、dispatch-candidate/reference、red.log。

使用新的 Python 3.11 venv，通过正常 pip 依赖解析安装本分支 wheel；`tests/send_auth/constraints.txt` 固定验证环境依赖。不要安装 Application。导出参考：

```sh
git show fa0983dcc56ca109555a33d90aac0fecca6bdf0d:plugins/taiko.py > "$EVIDENCE/reference.py"
```

复用 Phase 2E-R 的 `fixture.py`（可从 `44aaf656:packages/taiko-application/tests/fixture.py` 导出，无需安装该包）、固定资源目录和既有普通 B30 PNG。输入 hash 见 `provenance.json`。将下列 Python 命令交给已有 QA wrapper，串行运行；输出及缓存放磁盘 `/var/tmp`：

```sh
python tests/send_auth/chain.py --host client --sandbox "$EVIDENCE/chain" \
  --installed "$VENV" --images "$FIXTURE_IMAGES" --fixture "$FIXTURE_PY" \
  --resources "$RESOURCES" --output "$EVIDENCE/normal.json"
# 同一命令加 --reference "$EVIDENCE/reference.py"，输出 reference.json。
# 同一命令加 --revoke --failure MODE，分别输出 MODE.json；MODE 为
# bind403、score403、timeout、identity、invalid-identity。
python tests/send_auth/dispatch.py --host client --sandbox "$EVIDENCE/dispatch" \
  --installed "$VENV" --images "$FIXTURE_IMAGES" --output "$EVIDENCE/dispatch-candidate.json"
# 同一分派命令加 --reference，输出 dispatch-reference.json。
python tests/send_auth/audit.py --repo "$CHECKOUT" --evidence "$EVIDENCE"
```

代码与报告仅作为独立热修补 PR，等待审阅。完成后停止。
