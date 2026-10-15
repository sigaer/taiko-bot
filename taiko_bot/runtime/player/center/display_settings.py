from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from .display_support.draw_dress import (
    MY_DON_SHOWCASE_LAYOUT_NICKNAME,
    normalize_my_don_showcase_layout,
)


def _normalize_title_name(value: object) -> str:
    return str(value or "").replace("\u3000", " ").strip()


@dataclass(frozen=True)
class WebMyDonShowcaseSettings:
    title_overrides: Tuple[str, ...] = ()
    showcase_layout: str = MY_DON_SHOWCASE_LAYOUT_NICKNAME


def load_web_mydon_showcase_settings(
    taiko_id: str | int, *, connection_factory,
) -> WebMyDonShowcaseSettings:
    taiko_id = str(taiko_id).strip()
    if not taiko_id:
        return WebMyDonShowcaseSettings()

    try:
        connection = connection_factory()
    except Exception:
        logging.exception("failed_to_connect_taiko_db_for_mydon_showcase taiko_id=%s", taiko_id)
        return WebMyDonShowcaseSettings()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT bindings.mydon_showcase_layout, titles.title_name
                FROM web_taiko_bindings bindings
                LEFT JOIN web_taiko_binding_mydon_showcase_titles titles
                    ON titles.binding_id = bindings.id
                WHERE bindings.taiko_id = %s
                ORDER BY titles.slot_index ASC, titles.id ASC
                """,
                (taiko_id,),
            )
            rows = cursor.fetchall()
    except Exception:
        logging.exception("failed_to_load_mydon_showcase_titles taiko_id=%s", taiko_id)
        return WebMyDonShowcaseSettings()
    finally:
        connection.close()

    resolved: list[str] = []
    seen = set()
    showcase_layout = MY_DON_SHOWCASE_LAYOUT_NICKNAME
    for row in rows:
        if isinstance(row, (list, tuple)):
            raw_layout = row[0] if row else None
            raw_title_name = row[1] if len(row) > 1 else None
        else:
            raw_layout = None
            raw_title_name = row
        try:
            showcase_layout = normalize_my_don_showcase_layout(raw_layout)
        except ValueError:
            logging.warning(
                "invalid_mydon_showcase_layout taiko_id=%s layout=%r",
                taiko_id,
                raw_layout,
            )
        title_name = _normalize_title_name(raw_title_name)
        if not title_name or title_name in seen:
            continue
        seen.add(title_name)
        resolved.append(title_name)
    return WebMyDonShowcaseSettings(tuple(resolved), showcase_layout)
