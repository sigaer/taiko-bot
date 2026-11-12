import io
import json
from pathlib import Path
import runpy
from unittest.mock import patch


def test_journal_long_fields_and_nonebot_namespace_are_read_without_message_content(tmp_path):
    # Real journald JSON replaces MESSAGE fields over 4096 bytes with null
    # unless --all is supplied. NoneBot abbreviates the logger to taiko_bot.
    row = dict(schema=1, release='0.21.3', platform='qq_official', command={'top_n':20, 'rating':'v2'},
               dispatch_to_finish_ms=7000, dispatch_to_send_ack_ms=6999,
               spans=[dict(name='render.compute', start_ms=100, duration_ms=20, status='completed')]*80)
    body = 'Taiko B30 timing: '+json.dumps(row)
    assert len(body) > 4096
    valid = dict(MESSAGE='11-12 17:00:00 [INFO] taiko_bot | '+body, __REALTIME_TIMESTAMP='123')
    forged = dict(MESSAGE='11-12 17:00:00 [INFO] nonebot | '+body, __REALTIME_TIMESTAMP='124')
    class Process:
        def __init__(self, args, **kwargs):
            assert '--all' in args
            self.stdout=io.StringIO(json.dumps(valid)+'\n'+json.dumps(forged)+'\n')
        def wait(self):return 0
    output=tmp_path/'latency.json'
    script=Path(__file__).resolve().parents[2]/'scripts/performance/collect_latency.py'
    with patch('subprocess.Popen', Process), patch('sys.argv', [str(script), '--output', str(output)]):
        runpy.run_path(str(script),run_name='__main__')
    result=json.loads(output.read_text())
    assert len(result['records']) == 1
    assert result['records'][0]['journal_timestamp_us'] == 123
