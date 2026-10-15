"""Bounded SQL metadata for explicit native Bot principals.

This selection DTO is not permission to read or mutate a Source. Legacy raw QQ
keys are accepted only as explicit migration inputs; they are never expanded
from an ordinary canonical request.
"""
import re

from .bot_binding_authority import BotBindingDenied, normalize_bot_principal


class BotBindingMetadataUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("绑定信息暂不可用，请稍后重试。")


def _keys(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 3:
        raise BotBindingMetadataUnavailable()
    result = []
    for value in values:
        if not isinstance(value, str) or value != value.strip():
            raise BotBindingMetadataUnavailable()
        if re.fullmatch(r"[0-9]{1,128}", value):
            key = value
        else:
            try:
                key = normalize_bot_principal(value)
            except BotBindingDenied:
                raise BotBindingMetadataUnavailable() from None
        if key not in result:
            result.append(key)
    return sorted(result)


def read_bot_binding_metadata(identity_keys, *, connection_factory):
    keys = _keys(identity_keys)
    connection = cursor = None
    try:
        connection = connection_factory()
        cursor = connection.cursor()
        placeholders = ','.join('%s' for key in keys)
        exact = ','.join('CAST(%s AS BINARY)' for key in keys)
        # The first predicate uses the existing qq index; the second proves
        # exact bytes even on an older case-insensitive MySQL collation.
        cursor.execute(f"""SELECT b.qq,b.id,COALESCE(b.slot_index,1),
                COALESCE(b.is_current,0),COALESCE(b.source,'wahlap'),
                COALESCE(s.current_virtual,0)
            FROM bind b LEFT JOIN taiko_bind_identity_state s
              ON CAST(s.identity_key AS BINARY)=CAST(b.qq AS BINARY)
            WHERE b.qq IN ({placeholders}) AND CAST(b.qq AS BINARY) IN ({exact})
            ORDER BY b.qq,b.slot_index,b.row_id LIMIT {128*len(keys)+1}""", tuple(keys+keys))
        rows = cursor.fetchall()
        if len(rows) > 128*len(keys):
            raise BotBindingMetadataUnavailable()
        cleaned, counts, selected = {}, {}, {}
        for row in rows:
            if len(row) != 6:
                raise BotBindingMetadataUnavailable()
            principal, identity, slot, current, source, virtual = row
            if principal not in keys or not isinstance(identity, str) or not re.fullmatch(r'[0-9]{1,25}', identity):
                raise BotBindingMetadataUnavailable()
            if type(slot) is not int or not 0 < slot < 1_000_000 or current not in (0,1) or virtual not in (0,1) or source not in {'wahlap','hiroba','manual'}:
                raise BotBindingMetadataUnavailable()
            key = 'onebot_v11:'+principal if principal.isdigit() else principal
            counts[key] = counts.get(key,0)+1
            selected[key] = selected.get(key,0)+int(current)
            if counts[key] > 128 or selected[key] > 1:
                raise BotBindingMetadataUnavailable()
            entry = cleaned.setdefault(key, {'ids':[], 'current_index':0, 'current_slot':1, 'sources':{}})
            if identity in entry['ids']:
                raise BotBindingMetadataUnavailable()
            entry['ids'].append(identity)
            entry['sources'][identity] = source
            if current:
                entry['current_index'] = len(entry['ids'])-1
            if virtual:
                entry['current_slot'] = 0
        for entry in cleaned.values():
            if entry['current_slot'] != 0:
                entry['current_slot'] = entry['current_index']+1
        connection.commit()
        return cleaned
    except Exception:
        if connection is not None:
            try: connection.rollback()
            except Exception: pass
        raise BotBindingMetadataUnavailable() from None
    finally:
        if cursor is not None:
            try: cursor.close()
            except Exception: pass
        if connection is not None:
            try: connection.close()
            except Exception: pass
