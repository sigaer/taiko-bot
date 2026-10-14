from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Any, Optional
from taiko_application.merged_bind import MaterializedMergedBind, MergedBindError, MergedBindMissingUserdataError, build_virtual_user_id
USERDATA_DIR=Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))/"userdata"

def materialize_merged_bind_userdata(
    identity_key: str,
    entry: Dict[str, Any],
    *,
    userdata_dir: Optional[Path] = None,
) -> MaterializedMergedBind:
    from taiko_store.merged_materialization import materialize
    from taiko_store.publication import PublicationError

    if not isinstance(entry, dict) or not isinstance(entry.get("ids"), (list, tuple)):
        raise MergedBindError("合并账户绑定无效。")
    ids = entry["ids"]
    if (not 2 <= len(ids) <= 128 or any(not isinstance(item, str) for item in ids)
            or len(set(ids)) != len(ids)):
        raise MergedBindError("当前绑定数量或账号无效，无法生成 u0 合并账户。")
    index = entry.get("current_index", 0) or 0
    if type(index) is not int:
        raise MergedBindError("合并账户资料来源无效。")
    index = max(0, min(index, len(ids) - 1))
    virtual_id = build_virtual_user_id(identity_key)
    root = Path(userdata_dir) if userdata_dir is not None else Path(os.getenv("TAIKO_USERDATA_DIR") or USERDATA_DIR)
    try:
        return materialize(root, identity_key, ids, ids[index], virtual_id)
    except (PublicationError, OSError, ValueError):
        raise MergedBindError("合并账户数据暂不可用，请更新真实账号后重试。") from None
