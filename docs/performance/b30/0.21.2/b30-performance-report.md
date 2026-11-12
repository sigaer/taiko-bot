# B30 全链路性能报告：Taiko Bot 0.21.2

代码基线：Bot 0.21.1 / Application 0.8.2，`cf66562d11128dad7c327d49ad665a45a2684eaf`。优化：Bot 0.21.2 / Application 0.8.3，`9e7f84d9352cee27305ec09192167ea0fcdde548`。核实 main 和生产均已超过原建议的 0.20.2，因此发布 0.21.2。

所有数字来自本次原始测量；旧耗时 / 新耗时为加速倍数。原始纳秒计时、独占/累计阶段、CPU、RSS、尺寸、字节数、哈希和环境逐条保存在同目录两份 JSON。

## 环境、样本与范围

Intel Xeon Platinum 8255C 2.50GHz，宿主 8 vCPU / 31 GiB RAM；所有测量使用现有 QA 隔离器：CPUQuota=200%，MemoryHigh=2 GiB，MemoryMax=3 GiB，SwapMax=256 MiB，每项最长 15 分钟。未清理宿主文件缓存，未提高生产资源限制。各进程负载和 cgroup 配额保留于原始 environment。

Python 3.11.4、Pillow 11.3.0、NumPy 2.4.6、Pandas 3.0.6，中心 Core 0.1.1 / Contract 0.1.0。客户端使用独立的已安装 Core 0.1.2 模块覆盖，保持相同 Python/Pillow。除 Bot/Application 外，115 个依赖、8667 个安装文件的版本及内容与旧发布逐一一致。没有以依赖升级换取性能。

固定种子 20261112、时刻 2026-11-11T12:00:00；冻结公共曲库、V2 CSV、字体和 6591 个相关资源文件。完整修订及资源 SHA256 位于 JSON 的 provenance。成绩、历史、绑定均为合成；没有读取其他玩家私有数据。固定输入保存在隔离目录，未提交任何玩家文件或资源包。

|样本|覆盖|成绩数|历史快照数|
|---|---|---:|---:|
|U01|无成绩|0|0|
|U02|少量成绩|3|0|
|U03|不满Top20|17|0|
|U04|不满Top30|27|0|
|U05|满Top30|30|0|
|U06|满Top50|50|0|
|U07|中等成绩量|350|0|
|U08|高密度成绩量|1520|0|
|U09|重复歌曲版本|112|0|
|U10|无历史|80|0|
|U11|正常30天历史|100|30|
|U12|长期全量及增量历史|350|180|
|U13|u0多账号合并|150|0|
|U14|长曲名多语言复杂装扮|50|0|

U09 包含重复谱面与旧版本 ID；U13 包含两个合成账号的 u0 合并；U14 使用实际公共多语言长曲名和合成装扮。额外 E01 仅 easy/normal/hard、E02 五难度混合、E03 全部低于 75% 精度，验证无可计分结果和非鬼谱语义。

中心端每个 U 样本覆盖 13 条命令：`taikob`、`taikob20 v2`、`taikob30 v2`、`taikob20 v1`、`taikob30 v1`、`taikob50 v1`、`taikob20 v2 精度`、`taikob30 v1 精度`、`taikob20 v2 体力`、`taikob20 v1 节奏`，以及 nonsense、-r、v1/v2 冲突。客户端每个 U 覆盖 `taikob20/30/50`、`taikob20 v2`、v2 精度/体力、非法 v2 Top30、非法维度；另有 48 个尺寸、维度别名、缺参、版本、空结果边界。完整命令逐条保存在 JSON。矩阵测 Application 参数端口；裸客户端 taikob 等不匹配 Matcher 的输入是参数边界探针，不代表生产会回复消息，真实 Matcher 覆盖另列。

中心默认 `taikob` 保持 v2 Top20，原版已不经过完整 v1 计算；客户端必须带 TopN（如 taikob20），省略评分版本时为 v1，裸 taikob 不匹配客户端 Matcher；v2 仅支持 Top20，其布局、重复版本策略和错误提示均保留。`taikob30 v1` 经 Application execute → 中心 B30 adapter → Application B30Renderer → 30 张 Single 卡片。客户端经自身 legacy renderer。

## 测量口径

六个主要场景各新进程 5 次；热缓存预热 3 次、正式 20 次。query 包括真实 PublicationStore 当前/历史对象读取、完整性验证、历史重建、计算和生产 JPEG 路径；身份为固定模拟端口，A 阶段还含合成 fixture 载入开销（两版一致）；真实 Matcher 指标另表列出。compute 使用预先读取的输入，每次仍新建请求级私人计算缓存；draw 使用固定 ScoreContext，测默认 PNG API 绘图及原编码包装，便于比较 API 本身。网络、平台发送和远端 SQL 延迟均不计入。

另以真实 NoneBot Matcher/Provider、只读合成 SQL authority 和真实 PublicationStore 测量完整 handler（4 个场景各 3+20 次）；包含授权算法及发送前复核，发送端仅记录图像哈希。没有通过真实 Bot 账号制造流量。

另有 phase-detail 六场景各 3+20 次，额外细分读取、曲库索引、六维/综合聚合、PNG 解码；其插桩开销不混入主要提速数字。阶段 A–F 使用 perf_counter_ns，保留父子关系。inclusive 为含子阶段累计值，exclusive 为扣除直接子阶段后的独占值，不能把各层 inclusive 相加。CPU 为 process_time_ns；峰值 RSS 为进程累计高水位，不能当作每请求净分配。P95 使用 nearest-rank。为固定离线数据，initialize 预载冻结 V2 CSV，其读取/解析计入 startup；冷进程 query 表示新 Python 进程内初始化后的首个查询，不含公网刷新，导入 startup 和外部进程总时长另存，后者还含隔离 fixture 初始化。

## 热缓存完整查询（秒）

|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|
|---|---:|---:|---:|---:|---:|---:|
|U05 taikob30 v1|3.653|0.620|3.767|0.708|5.89×|83.0%|
|U05 taikob|2.589|0.397|2.859|0.456|6.53×|84.7%|
|U08 taikob30 v1|3.843|0.990|4.087|1.203|3.88×|74.2%|
|U08 taikob|2.622|0.448|2.781|0.611|5.85×|82.9%|
|U11 taikob|2.820|0.519|3.006|0.573|5.43×|81.6%|
|U12 taikob|3.252|0.812|3.409|0.970|4.00×|75.0%|

## 已准备数据后的完整计算与生产绘图（秒）

|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|
|---|---:|---:|---:|---:|---:|---:|
|U05 taikob30 v1|3.641|0.605|3.754|0.684|6.02×|83.4%|
|U05 taikob|2.665|0.400|2.892|0.436|6.65×|85.0%|
|U08 taikob30 v1|3.950|0.984|4.125|1.205|4.01×|75.1%|
|U08 taikob|2.507|0.443|2.525|0.473|5.66×|82.3%|
|U11 taikob|2.695|0.430|2.961|0.437|6.26×|84.0%|
|U12 taikob|2.841|0.488|3.047|0.549|5.83×|82.8%|

## 纯绘图：默认 PNG API 与编码（秒）

|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|
|---|---:|---:|---:|---:|---:|---:|
|U05 taikob30 v1|3.502|1.256|3.685|1.497|2.79×|64.1%|
|U05 taikob|2.487|0.956|2.764|1.016|2.60×|61.6%|
|U08 taikob30 v1|3.331|1.200|3.499|1.270|2.78×|64.0%|
|U08 taikob|2.271|0.903|2.476|0.967|2.51×|60.2%|
|U11 taikob|2.401|0.945|2.531|1.019|2.54×|60.7%|
|U12 taikob|2.425|0.935|2.641|0.987|2.59×|61.4%|

## 冷进程内首个完整查询（秒）

|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|
|---|---:|---:|---:|---:|---:|---:|
|U05 taikob30 v1|4.052|1.441|4.264|2.132|2.81×|64.4%|
|U05 taikob|3.025|1.313|3.122|1.348|2.30×|56.6%|
|U08 taikob30 v1|4.244|1.786|4.424|2.633|2.38×|57.9%|
|U08 taikob|3.116|1.555|3.281|1.574|2.00×|50.1%|
|U11 taikob|3.295|1.463|3.378|2.147|2.25×|55.6%|
|U12 taikob|4.109|1.922|4.618|2.100|2.14×|53.2%|

## 真实 Matcher 完整链路（秒）

|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|
|---|---:|---:|---:|---:|---:|---:|
|U05 taikob30 v1|3.781|0.601|4.050|0.630|6.29×|84.1%|
|U05 taikob|2.675|0.402|2.868|0.436|6.65×|85.0%|
|U08 taikob|2.653|0.457|2.867|0.618|5.81×|82.8%|
|U12 taikob|3.539|1.060|3.687|1.195|3.34×|70.1%|

## 冷进程初始化与外部总时长（秒）

|样本/命令|旧初始化 P50/P95|新初始化 P50/P95|旧外部进程 P50/P95|新外部进程 P50/P95|
|---|---|---|---|---|
|U05 taikob30 v1|2.056 / 2.212|2.151 / 2.182|6.771 / 6.823|4.233 / 4.957|
|U05 taikob|1.987 / 2.105|2.068 / 2.106|5.653 / 5.685|3.966 / 4.109|
|U08 taikob30 v1|1.980 / 2.056|2.077 / 2.506|6.885 / 6.956|4.515 / 5.817|
|U08 taikob|2.057 / 2.181|2.038 / 2.154|5.769 / 5.912|4.223 / 4.235|
|U11 taikob|2.091 / 2.123|2.065 / 2.296|6.042 / 6.108|4.440 / 5.001|
|U12 taikob|2.117 / 2.280|2.116 / 2.267|7.488 / 8.168|5.257 / 5.567|

初始化为冻结输入下的模块/资源加载阶段；外部进程总时长还包含解释器、fixture PublicationStore 写入和测试脚手架，不作为生产请求耗时或提速目标。冷查询与热缓存指标分别报告。

## CPU、内存和输出

|样本/命令|旧 CPU P50 秒|新 CPU P50 秒|旧峰值 RSS MiB|新峰值 RSS MiB|尺寸|JPEG 字节|
|---|---:|---:|---:|---:|---|---:|
|U05 taikob30 v1|3.653|0.620|354.3|324.8|[1080, 3030]|775796|
|U05 taikob|2.589|0.396|354.3|326.7|[1080, 2436]|581145|
|U08 taikob30 v1|3.839|0.990|363.5|332.8|[1080, 3030]|799810|
|U08 taikob|2.621|0.448|363.5|333.5|[1080, 2436]|591909|
|U11 taikob|2.819|0.519|364.3|340.0|[1080, 2436]|609652|
|U12 taikob|3.252|0.812|402.1|356.9|[1080, 2436]|600119|

## 分项优化及局部复测

每步以相同六场景执行一次未预热的隔离查询。以下为实测毫秒及相对前一步倍数，仅用于定位来源，单次采样受冷资源和负载影响，正式结论以上方 20 次分布为准。历史聚合的最后一轮是在有界执行器接入后补测，未伪装成早期测量。

|步骤|标准 v1|默认 v2|密集 v1|密集 v2|30 天历史|180 天历史|
|---|---:|---:|---:|---:|---:|---:|
|旧版|4292.4|4144.0|4125.4|2873.0|2926.2|3422.3|
|单卡直接 Image|2567.4 (1.67×)|1871.0 (2.21×)|2465.9 (1.67×)|1793.1 (1.60×)|1912.0 (1.53×)|2609.7 (1.31×)|
|同参数 Rating 复用|2836.7 (0.91×)|1879.7 (1.00×)|2545.5 (0.97×)|1836.9 (0.98×)|1997.2 (0.96×)|2351.9 (1.11×)|
|共享字体模板与封面|2157.6 (1.31×)|1348.1 (1.39×)|1890.4 (1.35×)|1359.1 (1.35×)|1562.1 (1.28×)|2062.6 (1.14×)|
|最终 JPEG 直出|1377.7 (1.57×)|1011.6 (1.33×)|1236.7 (1.53×)|790.1 (1.72×)|981.8 (1.59×)|1415.7 (1.46×)|
|公共曲库及索引|1410.8 (0.98×)|746.7 (1.35×)|1204.2 (1.03×)|621.2 (1.27×)|770.4 (1.27×)|1298.7 (1.09×)|
|修订失效完善|1395.8 (1.01×)|620.6 (1.20×)|1191.8 (1.01×)|601.7 (1.03×)|753.6 (1.02×)|1335.9 (0.97×)|
|历史窗口重建|1432.0 (0.97×)|600.3 (1.03×)|1142.1 (1.04×)|645.4 (0.93×)|740.7 (1.02×)|1058.0 (1.26×)|
|v2/维度图资源|1444.3 (0.99×)|615.6 (0.98×)|1146.2 (1.00×)|593.3 (1.09×)|777.6 (0.95×)|1090.7 (0.97×)|
|相同尺寸 resize 消除|1415.8 (1.02×)|539.9 (1.14×)|1109.7 (1.03×)|642.8 (0.92×)|765.5 (1.02×)|1049.2 (1.04×)|
|纯计算线程边界|1515.3 (0.93×)|596.8 (0.90×)|1196.1 (0.93×)|675.0 (0.95×)|876.8 (0.87×)|1167.6 (0.90×)|
|相同输入历史六维复用|1442.2 (1.05×)|568.4 (1.05×)|1210.7 (0.99×)|606.5 (1.11×)|763.4 (1.15×)|960.3 (1.22×)|

早期局部记录尚未加入总 manifest SHA256 字段；其六个固定输入未变，各步最终 JPEG 哈希逐一相同。正式前后测试每行均包含最终冻结 manifest SHA256，不以局部单次采样替代正式验收。

单卡不再做 30 次 PNG 编码/解码，使用相同 LANCZOS 与尺寸。请求级共享只读资源、先复制模板再写玩家内容；跨请求仅缓存公共图片，限额 64 MiB。字体请求限额 128、私人 Rating memo 32 项/32000 行、同输入聚合 64 项；不缓存最终私人图片。

v1 预计算仅在评分 profile、去重策略、用户、完整有序成绩摘要与曲库修订相同才复用。v2 使用自身结果；删除重复全量计算前保留了无可计分结果的旧判定语义。历史只保留需要的最近窗口，仍按原完整+增量序列重放；相同快照 Rating/六维在请求内复用，未启用跨玩家私人历史缓存，未改变每日归档行为。

公共 JSON/Rating/index/重复版本/V2 CSV 按路径、mtime_ns、size、inode、ctime 修订失效。测试发现宿主 4ms 时间戳粒度可能让快速同尺寸写入别名，修复为新近文件校验内容摘要、图片新近更新暂不跨请求缓存；相关失败测试修复后原断言全部通过。没有降低图像质量或修改评分公式。

Pillow 操作仅删除可证明相同的操作；标题截断、布局搜索、雷达图和非等尺寸缩放保留原算法与滤镜。Matplotlib 分支保留主线程并占用相同并发预算，避免 pyplot 线程不安全；其本身仍可能短暂阻塞事件循环。局部步骤出现单次噪声/无收益时没有把其标成稳定加速；收益主要来自资源复用与编码消除。

## 图片、算法及授权验收

命令矩阵与扩展边界共 342 项，输出全部与旧版一致。327 项全量 Rating 结果摘要、92 项 TopN/综合/六维/趋势/历史差异/NEW 计算摘要一致；256 项默认 PNG 字节 SHA256 与解码像素一致；256 项生产编码前 RGB/原始像素与尺寸一致。最终 JPEG 字节、尺寸、像素和长度均一致（quality=85、optimize=True，透明区域原白底处理）。

原 Application Phase 2B 的 25 项图片/缺资源用例全部通过；使用原 provenance 与哈希，没有更新 golden 来适应新输出。安装包 standalone 4 项通过。中心/客户端真实 Matcher 各 40 项，覆盖 OneBot/QQ、普通/u0、准备后/渲染后/发送时撤权、成员/顺序/当前档案变更及解绑，SQL 与 PublicationStore lease 均留在主线程，无真实发送。

主回归 46 项、客户端 V2/可见性 7 项、已安装 wheel cache smoke 4 项均通过。执行器另测限额、队列拒绝、取消、超时、异常及启动关闭；取消后协作停止，实际工作结束前不归还占用，最多 2 个绘图和 1 个等待请求。

异常注入曾发现初版使用 Pillow Image 上下文管理器没有显式释放内存像素对象。生产未部署该包；改为明确关闭卡片、Alpha 通道及解码源，新增成功/异常关闭与借入图像保留测试。最终包的全套 after 测量重新执行，初版结果与失败日志另存 intermediate-with-pillow-context，不混入最终结论。

## 并发与资源生命周期

|并发|旧请求 P50/P95 秒|新请求 P50/P95 秒|P95 加速|旧/新吞吐 req/s|旧/新事件循环最大间隔 秒|
|---:|---|---|---:|---|---|
|2|5.054 / 6.601|0.777 / 0.949|6.95×|0.316 / 2.144|6.864 / 0.093|
|3|6.448 / 10.089|1.363 / 1.846|5.47×|0.304 / 1.679|10.339 / 0.383|

每档 20 批，混合 v1/v2 与长期历史。三请求包含等待时间；旧版同步串行，新版两个 worker，不把线程池收益算作单次算法提速。

|版本|预热 RSS MiB|第50次|第100次|轮换14用户至128次|公共缓存 MiB/上限|
|---|---:|---:|---:|---:|---|
|before|317.2|349.1|349.2|340.8|无进程图片缓存|
|after|331.3|321.3|321.2|320.5|33.76 / 64|

|连续绘图分组|旧 P50 秒|新 P50 秒|
|---|---:|---:|
|1–10|3.910|0.743|
|11–20|3.758|0.612|
|21–30|3.731|0.641|
|31–40|3.763|0.597|
|41–50|3.787|0.669|
|51–60|3.718|0.586|
|61–70|3.779|0.608|
|71–80|3.674|0.592|
|81–90|3.642|0.874|
|91–100|3.697|0.682|

新版末20次 P50 / 初20次 P50 = 1.152，该轮后段存在短时耗时波动，上表不呈持续单调变慢；未把这一波动解释为优化收益。RSS 后半程保持平台，完整逐次数据保留。

连续同用户100次、不同用户轮换28次与混合并发均完成，无 OOM；逐次原始 RSS、耗时及周期采样在 JSON 中。三次实际第三卡异常验证所有请求拥有的 Pillow 图片关闭，后续请求恢复；新执行器重复完整启动/关闭3次，最终无 active/admitted。资源缓存有界且失效测试通过。

## 阶段证据（独立详细采样，热查询均值毫秒）

|场景/阶段|旧累计|新累计|旧独占|新独占|
|---|---:|---:|---:|---:|
|taikob30 v1 / C.top_diff._pick_top_entries|5.52|6.86|5.38|6.67|
|taikob30 v1 / C.v1._compute_results_from_userdata_records|7.68|3.89|7.68|3.89|
|taikob30 v1 / C.v1.compute_all_from_userdata_records|17.69|0.00|0.48|0.00|
|taikob30 v1 / D.catalog.load_rating_config|27.12|0.00|27.12|0.00|
|taikob30 v1 / D.font|48.87|4.02|48.87|4.02|
|taikob30 v1 / D.open|28.45|0.80|28.45|0.80|
|taikob30 v1 / E.B30Renderer._compose_resizable_template|70.72|70.22|7.01|7.31|
|taikob30 v1 / E.B30Renderer._render|3310.64|507.07|14.55|13.72|
|taikob30 v1 / E.B30Renderer._render_radar_image|14.01|13.88|12.76|12.65|
|taikob30 v1 / E.B30SingleRenderer._render|2131.00|195.95|207.77|193.27|
|taikob30 v1 / E.alpha_composite|84.51|83.77|84.17|83.43|
|taikob30 v1 / E.convert|708.42|31.47|81.46|26.59|
|taikob30 v1 / E.decode.PNG|713.98|4.71|712.37|4.68|
|taikob30 v1 / E.encode.JPEG|30.33|30.93|30.32|30.92|
|taikob30 v1 / E.encode.PNG|1878.84|0.00|1878.69|0.00|
|taikob30 v1 / E.resize|706.96|358.63|326.20|166.48|
|taikob30 v1 / F.request|3674.35|589.24|193.37|29.47|
|taikob / D.font|34.23|4.30|34.23|4.30|
|taikob / D.open|20.44|0.83|20.44|0.83|
|taikob / E.B30Renderer._compose_resizable_template|36.94|37.00|6.02|6.09|
|taikob / E.B30Renderer._render|2360.11|350.14|12.79|13.59|
|taikob / E.B30Renderer._render_radar_image|14.02|15.40|12.78|14.02|
|taikob / E.B30SingleRenderer._render|1460.43|136.61|142.77|134.19|
|taikob / E.alpha_composite|45.77|45.81|45.51|45.55|
|taikob / E.convert|509.09|23.77|56.43|18.77|
|taikob / E.decode.PNG|522.13|4.88|520.98|4.84|
|taikob / E.encode.JPEG|24.08|24.13|24.08|24.13|
|taikob / E.encode.PNG|1355.08|0.00|1354.97|0.00|
|taikob / E.resize|493.90|247.17|228.21|114.58|
|taikob / F.request|2653.56|413.29|182.27|18.60|

## 发布与剩余瓶颈

安装包版本和物理模块路径由生产进程启动日志中的 runtime inventory 核对。发布仅切换 taiko-bot.service，不重启 Viewer、同步接收器或其他游戏。原运行架构只有 37564 监听，37563 在基线即无监听；保持实际端口和既有连接方式，没有为迁就旧架构描述额外创建服务。

生产已于 2026-11-12 16:11:29 CST 切换至 0.21.2。至 16:23:34 仍为同一 PID、零重启，原 15 个 OneBot 连接的账户集合哈希完全恢复；其余五项服务 PID 及 systemd 单元保持不变。生产 cgroup MemoryCurrent 为 449.89 MiB，包含实际业务流量，不用重启前后的差值声称优化收益。

部署后以实际 current 解释器、已安装模块和冻结输入离线复验六个场景，JPEG 字节、像素、尺寸、长度均与基线逐项相同。此次使用用户明确批准的一次受限并行 QA（2 CPU、3 GiB、15 分钟），另一项上传继续运行；耗时不进入正式性能结论，没有通过真实 Bot 发送测试请求。

部署证据（同目录 deployment.json）：

```json
{
  "status": "PASS_deployed",
  "code_commit": "9e7f84d9352cee27305ec09192167ea0fcdde548",
  "versions": {
    "taiko-bot": "0.21.2",
    "taiko-application": "0.8.3"
  },
  "git_tags": [
    "v0.21.2",
    "application-v0.8.3"
  ],
  "wheel_sha256": {
    "taiko_application-0.8.3-py3-none-any.whl": "9f55914c754ca387cbf877c127b3e6100a481ba094a392d34ed170e3ba51b1be",
    "taiko_bot-0.21.2-py3-none-any.whl": "2ad8dc9ba2a8d49b36e41a021c8676bc8f6eaa11544d28aac54c1281902ec54e"
  },
  "artifact_directory": "/opt/taiko-bot/artifacts",
  "deploy_command": "TAIKO_DEPLOY_BOT_ONLY=1 scripts/deploy_taiko.sh 0.21.2 0",
  "before": {
    "timestamp": "2026-11-12T08:11:27.521782+00:00",
    "release": "/opt/taiko-bot/releases/0.21.1",
    "services": {
      "taiko-bot": {
        "MainPID": "1932398",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:23 CST",
        "MemoryCurrent": "877445120",
        "ActiveState": "active"
      },
      "taiko-public-api": {
        "MainPID": "1932286",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:22 CST",
        "MemoryCurrent": "122163200",
        "ActiveState": "active"
      },
      "taiko-sync-receiver": {
        "MainPID": "1932290",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:22 CST",
        "MemoryCurrent": "18595840",
        "ActiveState": "active"
      },
      "taiko-viewer": {
        "MainPID": "1914718",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 11:52:33 CST",
        "MemoryCurrent": "1201512448",
        "ActiveState": "active"
      },
      "taiko-song-update": {
        "MainPID": "1932294",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:22 CST",
        "MemoryCurrent": "34676736",
        "ActiveState": "active"
      },
      "taiko-memory-monitor": {
        "MainPID": "3751671",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Fri 2026-09-18 15:35:20 CST",
        "MemoryCurrent": "14827520",
        "ActiveState": "active"
      }
    },
    "ports": {
      "37563": false,
      "37564": true
    },
    "connected_bot_count": 15,
    "connected_bot_set_sha256": "856a9f447628b5267f0d85db2422eb330d4abdd9c55c176a29e16c9eb8b1a272",
    "actual_process_inventory": null
  },
  "after": {
    "timestamp": "2026-11-12T08:23:34.045028+00:00",
    "release": "/opt/taiko-bot/releases/0.21.2",
    "services": {
      "taiko-bot": {
        "MainPID": "2206583",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 16:11:29 CST",
        "MemoryCurrent": "471744512",
        "ActiveState": "active"
      },
      "taiko-public-api": {
        "MainPID": "1932286",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:22 CST",
        "MemoryCurrent": "122163200",
        "ActiveState": "active"
      },
      "taiko-sync-receiver": {
        "MainPID": "1932290",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:22 CST",
        "MemoryCurrent": "18595840",
        "ActiveState": "active"
      },
      "taiko-viewer": {
        "MainPID": "1914718",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 11:52:33 CST",
        "MemoryCurrent": "1303388160",
        "ActiveState": "active"
      },
      "taiko-song-update": {
        "MainPID": "1932294",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Thu 2026-11-12 12:08:22 CST",
        "MemoryCurrent": "34676736",
        "ActiveState": "active"
      },
      "taiko-memory-monitor": {
        "MainPID": "3751671",
        "NRestarts": "0",
        "ExecMainStartTimestamp": "Fri 2026-09-18 15:35:20 CST",
        "MemoryCurrent": "14905344",
        "ActiveState": "active"
      }
    },
    "ports": {
      "37563": false,
      "37564": true
    },
    "connected_bot_count": 15,
    "connected_bot_set_sha256": "856a9f447628b5267f0d85db2422eb330d4abdd9c55c176a29e16c9eb8b1a272",
    "actual_process_inventory": {
      "python": "3.11.4",
      "executable": "/opt/taiko-bot/current/bin/python",
      "packages": {
        "taiko-bot": {
          "version": "0.21.2",
          "module": "/opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages/taiko_bot/__init__.py"
        },
        "taiko-application": {
          "version": "0.8.3",
          "module": "/opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages/taiko_application/__init__.py"
        },
        "sakura-taiko-core": {
          "version": "0.1.1",
          "module": "/opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages/sakura_taiko_core/__init__.py"
        },
        "sakura-taiko-contract": {
          "version": "0.1.0",
          "module": "/opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages/sakura_taiko_contract/__init__.py"
        },
        "Pillow": {
          "version": "11.3.0",
          "module": "/opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages/PIL/__init__.py"
        }
      },
      "numpy": "2.4.6",
      "pandas": "3.0.6"
    }
  },
  "other_service_pids_unchanged": [
    "taiko-public-api",
    "taiko-sync-receiver",
    "taiko-viewer",
    "taiko-song-update",
    "taiko-memory-monitor"
  ],
  "service_unit_unchanged": true,
  "postdeploy_offline_verification": {
    "status": "PASS",
    "cases": 6,
    "qa_id": "qa-d2a888771359",
    "one_time_parallel_qa_authorized": true,
    "limits": {
      "cpu.max": "200000 100000",
      "memory.high": "2147483648",
      "memory.max": "3221225472",
      "memory.swap.max": "268435456"
    },
    "runtime_max_seconds": 900,
    "excludes_performance_conclusions": true,
    "real_bot_test_traffic": false,
    "cases_verified": [
      {
        "user": "U05",
        "command": "taikob30 v1",
        "output": {
          "kind": "image",
          "sha256": "a44d9dec8beb5ce1cdfedaa83ae6a50c2839ad58869d542e5201b9e57e093ac4",
          "pixels": "b9d0a533ca1f840b2cdf453ad07ca3fead0d08d1fdb06684959f91a316476bd1",
          "size": [
            1080,
            3030
          ],
          "bytes": 775796
        }
      },
      {
        "user": "U05",
        "command": "taikob",
        "output": {
          "kind": "image",
          "sha256": "77ce44d87a9f3bba49eccdf66f56df4ca28512fdfe65dd977ed974e1609b68f6",
          "pixels": "0b279f4e414efc4238ce0c4b92c37165dced4f01311edd47fbce56b5e3bf1929",
          "size": [
            1080,
            2436
          ],
          "bytes": 581145
        }
      },
      {
        "user": "U08",
        "command": "taikob30 v1",
        "output": {
          "kind": "image",
          "sha256": "3882ec5355ab56b1f283cd4897b1c50c29e99fa6b4da2c90a0d29d782751c62c",
          "pixels": "3388053ff7b9e368e0245aa49077ec793a797b7e52a61d570c62b8d019d74a36",
          "size": [
            1080,
            3030
          ],
          "bytes": 799810
        }
      },
      {
        "user": "U08",
        "command": "taikob",
        "output": {
          "kind": "image",
          "sha256": "16a2cd20ed7388dd91b4e83ae6692126b34e0df6c87c8e7faae98aaeec321adc",
          "pixels": "0c9f6c226ebaf77bbb3e32a98a12706d0cd5e880d050351c31903562075e407c",
          "size": [
            1080,
            2436
          ],
          "bytes": 591909
        }
      },
      {
        "user": "U11",
        "command": "taikob",
        "output": {
          "kind": "image",
          "sha256": "785048d674c32032fec4106118844ee7e123c89f6cea6cabb9b89d9a00477fa7",
          "pixels": "d9e05ba426a795f7306c79cfc8637c2e8b93645fb4f1daeeeb0a6099f2429c71",
          "size": [
            1080,
            2436
          ],
          "bytes": 609652
        }
      },
      {
        "user": "U12",
        "command": "taikob",
        "output": {
          "kind": "image",
          "sha256": "e6ffec012a74d75ef53b871364ae459977cb952d49684881069b27acfd5c398d",
          "pixels": "08bafbed843cb0dbbd80f9c2ed33f3e79584698a2121d8c13538b62513a0d2b9",
          "size": [
            1080,
            2436
          ],
          "bytes": 600119
        }
      }
    ]
  },
  "rollback_release_preserved": "/opt/taiko-bot/releases/0.21.1",
  "memory_note": "MemoryCurrent is service cgroup accounting under live traffic; it is not isolated peak RSS and its before/after difference is not a performance conclusion. Stability and leaks are assessed by the separate controlled 100-render stress test."
}
```

旧 `/opt/taiko-bot/releases/0.21.1`、原依赖包及代码基线保留。回滚：`TAIKO_DEPLOY_BOT_ONLY=1 scripts/deploy_taiko.sh 0.21.1 0`。源代码与安装包发布来自本报告代码提交；报告自身的后续提交不改变已验收 wheel。

剩余主要耗时为固定布局的文字/卡片合成、JPEG 编码及长期历史真实重建；密集成绩排序/Rating 仍遵守原算法。冷进程导入、系统字体初始化及文件系统读取不能由热缓存收益代替。网络、真实远端 SQL 和平台传输不在离线数字中；真实 handler 已验证本地算法/授权边界。没有改变生产玩家数据、授权、绑定、每日历史档案或其他服务。

最终基准中的旧版 query/compute/draw/cold 使用 before-confirmed 重测；最初直接返回固定 V2 snapshot 的初测保留在隔离证据目录，不混入最终统计。

复现：先用 fixtures.py 固定公共资源与合成输入；通过现有 run_qa.sh 分别以旧/新已安装解释器运行 run_cohorts.py、stress.py 和 host_events.py。每次使用相同冻结 fixture，完整命令与实施脚本位于 scripts/performance。测试及构建原始日志保留在 /home/sigaer/taiko/qa-vault/runs，隔离输入和步骤证据保留在 /var/tmp/taiko-b30-performance。
