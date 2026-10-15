# Frozen Sakura 458ceae removal target semantics.
def _resolve_bind_remove_target(entry: Dict[str, Any], target: str) -> Tuple[int, str]:
    ids = list(entry.get("ids") or [])
    if not ids:
        raise ValueError("当前没有可删除的鼓众广场ID。")

    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    target = str(target or "").strip()
    if not target:
        return current_index, ids[current_index]

    slot_match = re.fullmatch(r"[uU]([1-9]\d*)", target)
    if slot_match:
        slot_index = int(slot_match.group(1)) - 1
        if slot_index < 0 or slot_index >= len(ids):
            raise ValueError(f"当前仅已绑定 u1~u{len(ids)}。")
        return slot_index, ids[slot_index]

    if target in ids:
        return ids.index(target), target

    if target.isdigit():
        raise ValueError("当前未绑定该鼓众广场ID。")

    raise ValueError(
        "参数错误，请使用 删除绑定 / 删除绑定 u2 / 删除绑定 123456 这类形式。"
    )
