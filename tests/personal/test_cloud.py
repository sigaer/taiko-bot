import asyncio
from taiko_bot.runtime.player import personal

def _should_trigger_tcloud_command(text):
    class Event:
        def get_message(self): return []
    original = personal.entry.helpers.extract_plain_text
    personal.entry.helpers.extract_plain_text = lambda event: text
    try: return asyncio.run(personal.cloud_eligible(Event()))
    finally: personal.entry.helpers.extract_plain_text = original


def test_tcloud_command_aliases():
    assert _should_trigger_tcloud_command("tcloud")
    assert _should_trigger_tcloud_command("/tcloud")
    assert _should_trigger_tcloud_command("太鼓词云")
    assert _should_trigger_tcloud_command("/太鼓词云")
    assert _should_trigger_tcloud_command("词云")
    assert _should_trigger_tcloud_command(" 太鼓词云 ")
    assert not _should_trigger_tcloud_command("太鼓词云 全部")
    assert not _should_trigger_tcloud_command("更新广场")
