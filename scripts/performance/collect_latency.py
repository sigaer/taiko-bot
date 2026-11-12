"""Read only B30 timing records from journald, never export message logs."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import subprocess


def percentiles(values):
    ordered = sorted(values)
    return dict(n=len(ordered), p50_ms=round(statistics.median(ordered), 3),
                p95_ms=round(ordered[math.ceil(len(ordered)*.95)-1], 3),
                min_ms=min(ordered), max_ms=max(ordered))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', default='15 minutes ago')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows, groups = [], defaultdict(list)
    process = subprocess.Popen(['journalctl', '-u', 'taiko-bot.service', '--since', args.since,
                                '-o', 'json', '--all', '--no-pager'], stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        try:
            entry = json.loads(line)
            message = entry.get('MESSAGE') or ''
            if not isinstance(message, str):
                continue
            message = re.sub(r'\x1b\[[0-9;]*m', '', message)
            prefix, separator, body = message.partition(' | ')
            namespace = prefix.rsplit(' ', 1)[-1]
            if not separator or namespace not in ('taiko_bot', 'taiko_bot.runtime.request_timing') or not body.startswith('Taiko B30 timing: '):
                continue  # A user's message containing the marker is not telemetry.
            row = json.loads(body.removeprefix('Taiko B30 timing: '))
            if not isinstance(row, dict) or row.get('schema') != 1:
                continue
        except (ValueError, TypeError):
            continue
        row['journal_timestamp_us'] = int(entry['__REALTIME_TIMESTAMP'])
        rows.append(row)
        command = row.get('command', {})
        key = (row['release'], row['platform'], command.get('top_n'), command.get('rating'),
               command.get('dimension'), command.get('dynamic'))
        groups[key].append(row)
    if process.wait() != 0:
        raise SystemExit('journalctl failed')
    summary = []
    for key, requests in groups.items():
        spans = defaultdict(list)
        for row in requests:
            totals = defaultdict(float)
            for span in row['spans']:
                totals[span['name']] += span['duration_ms']
            for name, total in totals.items():
                spans[name].append(total)
        ack = [row['dispatch_to_send_ack_ms'] for row in requests
               if row['dispatch_to_send_ack_ms'] is not None]
        summary.append(dict(group=dict(zip(('release', 'platform', 'top_n', 'rating', 'dimension', 'dynamic'), key)),
                            requests=len(requests),
                            dispatch_to_finish=percentiles([r['dispatch_to_finish_ms'] for r in requests]),
                            dispatch_to_send_ack=percentiles(ack) if ack else None,
                            spans_inclusive={name: percentiles(values) for name, values in sorted(spans.items())}))
    report = dict(schema=1, collected_at=datetime.now(timezone.utc).isoformat(), since=args.since,
                  boundary='Adapter dispatch to send API acknowledgement; excludes client and pre-dispatch network latency',
                  warning='Spans are inclusive and may be nested; do not sum their durations. Small sample percentiles are descriptive only.',
                  records=rows, summary=summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(records=len(rows), summary=summary), ensure_ascii=False))


if __name__ == '__main__':
    main()
