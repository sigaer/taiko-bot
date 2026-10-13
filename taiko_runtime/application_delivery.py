"""Recheck host authority immediately before delivering a private command result."""


async def deliver_private_result(matcher, event, result, original, *, resolve, finish_text, deliver):
    if result is None:
        return
    try:
        current = resolve(event)
        fields = ("identity_key", "user_id", "source", "is_virtual")
        allowed = (
            isinstance(current, dict)
            and not current.get("error")
            and bool(current.get("user_id"))
            and all(current.get(key) == original.get(key) for key in fields)
        )
    except Exception:
        allowed = False
    if not allowed:
        await finish_text(matcher, event, "授权已失效，请重新查询。")
        return
    await deliver(matcher, event, result)
