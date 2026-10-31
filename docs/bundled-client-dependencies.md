# 客户端同仓依赖

客户端用 `python -m pip install -r requirements.txt` 安装全部本地项目与 PyPI 运行依赖。安装不使用 Git URL、SSH、外部源码目录或私有 wheelhouse。

- `packages/sakura-taiko-core`：Core 0.1.2，源提交 `0b7319d94b041daafb0a0d32e3ccc95e50da8810`，仅纳入领域库源码及构建声明。
- `packages/sakura-taiko-contract`：现有 Python Contract 0.1.0，不改动 Developer API v1 的 Contract 1.1 或 ResourceGrant。
- `packages/python-memory-runtime`：既有 runtime_memory 1.1.0 源码，缓存预算与算法不变。
- `packages/taiko-application`：现有 Application 0.8.1。

这批代码纳入本仓维护，不随安装访问原仓库。不包含生产配置、成绩、资源包或生成目录。中心现有 Core 0.1.1 profile 保持独立安装约束。
