"""Optional startup preparation using the existing immutable catalog owner."""
import asyncio
import logging
import os

from . import provider

logger = logging.getLogger(__name__)


def register_startup():
    from nonebot import get_driver
    try:
        driver = get_driver()
    except ValueError:
        # Pure message builders also import this package without a Bot driver.
        return False
    driver.on_startup(prewarm)
    return True


async def prewarm():
    if os.environ.get('TAIKO_SONG_QUERY_PREWARM') != '1':
        return False
    try:
        await asyncio.to_thread(provider.get_snapshot)
        return True
    except Exception as error:
        logger.warning('Public song prewarm failed (%s); lazy query recovery retained', type(error).__name__)
        return False
