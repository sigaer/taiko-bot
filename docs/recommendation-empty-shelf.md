# 推荐空上架集合边界修复

基线：taiko-bot main `6ee39935532914cbf20dccc2d5581c53ba9cf8af`（0.16.3）。
审查依据：[PR #10 P2](https://github.com/sigaer/taiko-bot/pull/10#discussion_r4310842532)。

center/recommendation_support 与 offline 的 `recommend_songs()` 各增加一次上架集合读取；可用谱面或上架集合任一为空时返回 `[]`。非空路径使用这次读取的同一集合委托 Core；default_ids、best_key、limit、谱面集合及其余参数不变。没有改 Rating、排序、身份规则、授权入口、依赖版本或 Viewer 代码；不发布版本、不部署、不读写生产曲库。

## 真实 Core 与可复现条件

验证安装 Core **0.1.1**，源码提交 `9fc0731358f6863c1e1efd9f1930a608850786f7`；Contract **0.1.0** 来自 Viewer `23f89b4f70e5a64ae76c33ac04c6c2d242808df1` 的 packages/sakura-taiko-contract。通过 GitHub 插件按 blob 获取源码，本地构建安装，未替换 Core 算法。

Core 的 `cn_available_chart_keys()` 本身过滤下架状态，因此一致的合并曲库/raw 快照全部下架时，available 也为空，已有保护即能拦截。这不能单独复现审查中的独立空过滤边界。新增 raw_only 场景：合并曲库所有歌曲下架，raw 快照仍含有一个不在合并曲库中的有效谱面；真实加载器因此得到 available 非空、shelf 为空。旧 Core 接受 available 中的该候选，修复后两个适配层均返回空。测试明确断言真实 Core 的旧结果非空，避免无候选夹具导致假通过。

## 验证

```sh
python -m unittest discover -s tests/recommendation -p test_empty_shelf.py -v
python -m compileall -q taiko_bot/offline/score_calculator.py taiko_bot/runtime/player/center/recommendation_support/score_calculator.py tests/recommendation/test_empty_shelf.py
git diff --check
```

- 1 个 unittest，包含 **168 个组合**：两个适配层 × 六种场景 × 七个维度 × limit 1/20，PASS。
- 场景：正常上架、部分下架、全部下架（含整数 1、字符串 1、已下架）、raw_only 边界、无有效谱面、空曲库。
- 正常/部分上架断言真实 Core 输出非空，并比较完整 DTO 列表，覆盖数值和顺序；断言上架/谱面成员与重复身份唯一性。夹具包含 21 个已玩谱面和未玩候选，覆盖 best20 排除及重复版本身份输入。
- 将两个入口暂时还原为基线逻辑后运行同一测试，恰好 **28 个失败组合**（两个入口 × 七维 × 两个 limit，全部为 raw_only）；恢复修复后全通过。
- 编译与 diff whitespace 检查 PASS。

测试沿用 wheel_cache_smoke.py 的 AST 隔离模式，直接编译仓库中两个薄适配函数和真实 JSON 加载器，调用安装态 Core 的建模、Rating 与推荐实现，仅向适配函数提供合成身份映射。它不模拟 Core，也不需要网络、私人数据、Bot driver 或图片渲染依赖；它不是完整模块导入、matcher/授权或 Viewer SQL/HTTP 端到端测试。本轮未重跑跨仓库端到端套件；不把既有跨入口一致性结论冒充本轮验证。授权和 Viewer 路径保持原样，审阅 diff 可确认本轮只改两个空集 guard。
