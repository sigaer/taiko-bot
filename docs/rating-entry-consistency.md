# Rating／六维／普通推荐接入修复

本轮为既有接入缺陷选择0.16.2 patch，Application0.8.1、中心Core0.1.1、客户端Core0.1.2及Contract0.1.0不改版本或公式。详见 Viewer [跨入口对照与证据](https://github.com/sigaer/taiko-viewer/blob/main/docs/rating-entry-consistency.md)。

修复 path-only 曲库LRU与import-time分组/visibility过期；聚合、B30卡片和普通推荐获取当前曲库身份。客户端初始化分组改为实际JSON读取。中心与客户端适配层对确认空的可用曲库返回空推荐，避免旧Core把空集合当作不限制。保留各Profile的去重、候选排序和显示规则。

`tests/recommendation/entry_consistency.py` 使用安装wheel的实际OneBot matcher、provider、解析/编排和原V1雷达聚合；与Viewer SQL/HTTP套件共享合成current/曲库，替换发送和非必要上游，观察推荐像素边界。`catalog_revision.py`验证安装模块的分组及visibility刷新；`wheel_cache_smoke.py`是CI的无外部依赖安装/缓存loader单元验证，不能代替前面的业务回归。

中心 `taikob` 默认v2；V1对照显式 `taikob20 v1 -r`。历史B30 collapse Profile与JSON Rating preserve不同，普通推荐仍按既有谱面身份合并版本。没有为了对齐数值修改公式、默认Profile或授权。
