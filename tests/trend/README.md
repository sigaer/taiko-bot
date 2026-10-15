# 趋势所有权验收

冻结基线：中心 Sakura `7c98214:taiko`、客户端 Taiko `e0b3e08`。
只从 Git 导出源码，运行目录的成绩、历史、绑定和公开曲库均为合成 fixture。

`events.py --host center|client --baseline <frozen-source> --work <isolated-dir>
--assets <public-assets> --application <taiko-checkout>` 比较真实 OneBot/QQ dispatch 的文本、
图片尺寸与 SHA256。正常业务必须有图片，不能以双方异常通过。

- 默认：v1/v2（中心）、N/窗口/维度、柱状/全部、错误参数，普通与 u0。
- `--representative`：两个命令的成功路径。
- `--mode security`：两个 matcher 的隐藏/未绑定/撤权、成员/顺序/profile 变化、
  发送失败复核、sourceView 混用拒绝，以及真实统计 recorder 无漏计/重复。
- `--history-only`：缺历史、低良率、无鬼里、相同/回退总曲数及日期窗口。
- `--archive`（中心）：实际命令独立源的 v1/v2 首次、热请求、当日更新、过去日期和
  保留期后图片/归档内容/持久化写入次数对照。
- `--native`（中心）：首次/热 native u0、成员/profile/current 更新与 publication 依赖一致。

网络、生产路径和渲染中的私人 I/O、写入、反向插件导入由 audit hook 拒绝。
`test_parsing.py` 和 `test_host.py` 保留原解析断言并验证同租约捕获、历史测量不重算。
完整存储和 Core/Application 验收不重复执行；补充 public9、tinfo、推荐、进度、B30 代表性回归。

通过 `scripts/memory/run_qa.sh` 串行运行，测试日志保存在隔离工作目录。
