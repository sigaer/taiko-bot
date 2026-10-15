"""同群其他 bot / 插件已占用的指令名，taiko 侧不再响应，避免一条消息双响。

以「进度」结尾的指令最容易撞车（taiko 的规则是 ``.+进度``），凡是别的 bot
已经实现的进度类指令，都在这里登记，新增时补一行即可。
"""

from __future__ import annotations

# 不属于 taiko 的「xx进度」指令（miku-bot：PJSK 进度查询与邀请活动进度/账单）
FOREIGN_PROGRESS_COMMANDS = (
    "任务进度",  # miku-bot 邀请活动：任务进度
    "账单进度",  # miku-bot 邀请活动：账单进度（管理员）
    "pjsk进度",  # miku-bot：PJSK 活动进度
    "twpjsk进度",
    "cnpjsk进度",
    "活动进度",  # miku-bot：活动查询
)


def is_foreign_progress_command(body: str) -> bool:
    """body 为去掉页码后的完整指令名，例如「任务进度」。"""
    normalized = str(body or "").strip().casefold()
    if not normalized:
        return False
    return any(normalized == word.casefold() for word in FOREIGN_PROGRESS_COMMANDS)
