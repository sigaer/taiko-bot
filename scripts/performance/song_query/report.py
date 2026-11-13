"""Validate and archive numeric evidence; never archive the real catalog."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def load(path):
    return json.loads(path.read_text())


def ms(value):
    return f'{value/1e6:.3f}'


def phases(value):
    return value.get('phases', value)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get('QA_RUN_ID'), 'Use the bounded QA runner'
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = load(args.work/'catalog/manifest.json')
    validation = load(args.work/'validation.json')
    assert validation['status'] == 'PASS'
    for name, row in manifest.items():
        data = (args.work/'catalog/songs'/name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row['sha256'], 'corpus changed'
    artifacts = []
    for path in sorted(args.work.glob('*.json')):
        shutil.copyfile(path, args.output/path.name)
        artifacts.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    lines = [
        '# 公共歌曲查询热路径：第一阶段性能证据', '',
        '日期：2026-11-13（Asia/Shanghai）。基线为最新 main `58174b5100a4f33800976b879abfab5ed1b77b9f` / '
        '已安装 Bot 0.23.0、Application 0.9.1。候选为本提交的 Bot 0.23.1、Application 0.9.2。', '',
        '本报告只衡量离线命令执行与中心端 `brief()`；不包含跨游戏前置路由、图片读取/落盘、QQ 请求或客户端拉图。'
        '没有生产部署，也不把离线收益当作线上回复耗时收益。', '',
        '## 环境与方法', '',
        '- 同一宿主机、Python 3.11.4、Linux 5.10.0-16-amd64、fuzzywuzzy 0.18.0 的纯 Python SequenceMatcher；未安装或替换 Levenshtein。',
        '- 中心端使用已安装 Core 0.1.1；客户端前后均加载仓库固定的 Core 0.1.2，未改变两端可见性和分组规则。',
        '- 所有负载串行经过现有 memory QA runner：MemoryHigh 2 GiB / Max 3 GiB、SwapMax 256 MiB、CPUQuota 200%、15 分钟/任务。'
        '单进程、单请求顺序回放，没有压生产服务、丢弃系统页缓存或并行构建。宿主机有正常业务负载，P95 是本次观测，不是 SLA。',
        '- 每端每版本 11 类主样本 × 40 次 = 440 次；额外真实部分曲名 40 次。前后各 960 次，共 1,920 个计时样本。'
        '每个用例先预热一次；P50/P95 取 nearest-rank。墙钟 perf_counter_ns、CPU process_time_ns。',
        '- 分阶段计时和逻辑文件 open/stat 计数单独回放，未混入主要延迟样本。读次数不代表物理磁盘 IOPS；操作系统页缓存保持自然状态。',
        '- 内存来自独立进程的 smaps_rollup RSS/PSS；额外 tracemalloc 进程估算首个查询后净保留 Python 分配量，'
        '其跟踪开销不混入延迟和未跟踪 RSS/PSS。', '',
        f'冻结输入：歌曲 {manifest["song_data.json"]["rows"]} 条 / {manifest["song_data.json"]["bytes"]:,} bytes；'
        f'别名记录 {manifest["song_alias.json"]["rows"]} 条 / {manifest["song_alias.json"]["bytes"]:,} bytes。', '',
    ]
    for name, row in manifest.items():
        lines.append(f'- `{name}` SHA-256 `{row["sha256"]}`')
    lines += ['', '## 延迟与 CPU', '',
              '单位 ms，单元格为 P50 / P95。`waruloo` 在这份真实曲库里已经是精确别名；'
              '不能把它的快速命中当作部分曲名收益，因此另测 `ワルルーさまの歌を`。', '']
    for profile in ('center', 'client'):
        old, new = (load(args.work/f'{state}-{profile}.json') for state in ('before', 'after'))
        assert old['fixture'] == new['fixture'] == manifest
        assert old['cases'] == new['cases']
        assert old['results'] == new['results'], f'command/brief drift: {profile}'
        lines += [f'### {profile}', '', '| 输入 | 原墙钟 | 新墙钟 | 原 CPU | 新 CPU |',
                  '|---|---:|---:|---:|---:|']
        for key, query in old['cases']:
            a, b = old['summary'][key], new['summary'][key]
            values = [f'{ms(item[metric]["p50"])} / {ms(item[metric]["p95"])}'
                      for metric in ('wall_ns', 'cpu_ns') for item in (a, b)]
            lines.append(f'| `{query}` | '+' | '.join(values)+' |')
        partial_old, partial_new = (load(args.work/f'{state}-partial-{profile}.json') for state in ('before', 'after'))
        assert partial_old['results'] == partial_new['results'], f'partial command drift: {profile}'
        for data in (partial_old, partial_new):
            assert data['details']['partial_name']['queries'][-1]['mode'] == 'partial_name', 'partial case is not partial'
        values = [f'{ms(item["summary"]["partial_name"][metric]["p50"])} / {ms(item["summary"]["partial_name"][metric]["p95"])}'
                  for metric in ('wall_ns', 'cpu_ns') for item in (partial_old, partial_new)]
        lines.append('| `ワルルーさまの歌を`（额外 40 次） | '+' | '.join(values)+' |')
        cpu_old = sum(sum(row['cpu_ns']) for row in old['raw'].values())/1e9
        cpu_new = sum(sum(row['cpu_ns']) for row in new['raw'].values())/1e9
        lines += ['', f'主样本 440 次总进程 CPU：{cpu_old:.3f} s → {cpu_new:.3f} s。', '']

    lines += ['## 分阶段归因与 I/O', '',
              '下表为额外单次带计时探针的中心端回放，单位 ms。加载、分组和匹配是嵌套阶段，不能相加；'
              '`brief` 包含它自己的读盘和解析。原调用路径是 `handle → execute_song → resolve_query → query_with_mode '
              '→ query_music → deliver/brief`。', '',
              '| 输入 | query 调用数 原/新 | 文件读取 原/新 | stat 原/新 | 文本读取 原/新 | JSON 解析 原/新 | 匹配 原/新 | 分组 原/新 | brief 原/新 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    before_trace, after_trace = (load(args.work/f'{state}-trace-center.json') for state in ('before', 'after'))
    for key in ('id', 'exact', 'alias', 'partial_name', 'homophone', 'fuzzy', 'prefix_exact', 'prefix_fuzzy'):
        a, b = (phases(trace[key]) for trace in (before_trace, after_trace))
        calls = lambda p, name: p.get(name, {}).get('calls', 0)
        duration = lambda p, name: p.get(name, {}).get('inclusive_ns', 0)
        lines.append(f'| {key} | {calls(a,"query_with_mode")} / {calls(b,"query_with_mode")} | '
                     f'{calls(a,"file_open")} / {calls(b,"file_open")} | {calls(a,"file_stat")} / {calls(b,"file_stat")} | '
                     f'{ms(duration(a,"read_text"))} / {ms(duration(b,"read_text"))} | '
                     f'{ms(duration(a,"json_loads"))} / {ms(duration(b,"json_loads"))} | '
                     f'{ms(duration(a,"matching"))} / {ms(duration(b,"matching"))} | '
                     f'{ms(duration(a,"center_groups"))} / {ms(duration(b,"center_groups"))} | '
                     f'{ms(duration(a,"brief"))} / {ms(duration(b,"brief"))} |')
    lines += ['', '前缀模糊样本实际执行四轮查询；旧实现每轮两次曲库读取，再由 brief 读一次歌曲文件。'
              '新实现请求内固定同一快照，稳态只在首次取得快照时 stat 两个输入。'
              '每 30 秒的内容复核会额外读取两个文件并计算哈希，内容相同不解析 JSON、不重建索引；'
              '实际发生更新时的构建/读盘不属于“零读取”的稳态情形。', '',
              '## 冷启动与内存代价', '',
              '| 模式 | 首次命令 原/新 ms | 首次后 RSS 原/新 MiB | 回放后 RSS 原/新 MiB | 回放后 PSS 原/新 MiB |',
              '|---|---:|---:|---:|---:|']
    memory_notes = []
    for profile in ('center', 'client'):
        a, b = (load(args.work/f'{state}-{profile}.json') for state in ('before', 'after'))
        lines.append(f'| {profile} | {ms(a["cold_first_command_ns"])} / {ms(b["cold_first_command_ns"])} | '
                     f'{a["memory_after_first"]["rss_kib"]/1024:.2f} / {b["memory_after_first"]["rss_kib"]/1024:.2f} | '
                     f'{a["memory_after_replay"]["rss_kib"]/1024:.2f} / {b["memory_after_replay"]["rss_kib"]/1024:.2f} | '
                     f'{a["memory_after_replay"]["pss_kib"]/1024:.2f} / {b["memory_after_replay"]["pss_kib"]/1024:.2f} |')
        retained = [load(args.work/f'{state}-allocation-{profile}.json')['retained_python_bytes']/1024**2
                    for state in ('before', 'after')]
        memory_notes += ['', f'{profile} 首个 ID 查询后净保留 Python 分配量：{retained[0]:.2f} → {retained[1]:.2f} MiB '
                  f'（差值 {retained[1]-retained[0]:+.2f} MiB；包括索引和字符读音准备，不等于进程总内存差）。', '']
        memory_notes += [f'{profile} 回放后的进程 RSS 差值 '
                  f'{(b["memory_after_replay"]["rss_kib"]-a["memory_after_replay"]["rss_kib"])/1024:+.2f} MiB；'
                  f'PSS 差值 {(b["memory_after_replay"]["pss_kib"]-a["memory_after_replay"]["pss_kib"])/1024:+.2f} MiB。', '']
    lines += memory_notes
    lines += ['索引以常驻内存换取请求延迟；只持有紧凑检索字段和不可变元组/映射，不保留完整谱面 JSON 树。'
              '所有曲目共享不可变字符读音集合，避免按整首曲名复制读音集合。每进程仅缓存一个 root/profile，'
              '旧 revision 仅由尚未结束的请求持有；没有按查询关键词无限增长的结果缓存。'
              '这些是一次离线回放的内存观测，未验证线上长期驻留或生产总体内存下降。', '',
              '## 正确性与更新边界', '',
              f'- 真实曲库每端 {validation["literal_queries_per_profile"]:,} 个不重复的曲名/ID/别名查询，'
              f'共 {validation["literal_comparisons_total"]:,} 次逐项差分；另有 120 次真实曲库阶段/开关组合差分，全部一致。',
              '- 保留原未索引 query_music 作为独立差分路径；未改变精确曲名 → ID → 精确别名 → 标准化曲名/别名 '
              '→ 同音 → 部分曲名 → 模糊匹配的顺序、候选顺序、分数和模糊并列取首规则。',
              '- 保留完整难度前缀精确词优先、中心端同曲分组和客户端可见性/不同版本 ID。',
              '- 请求从 execute_song 的前缀重试到 await deliver/brief 固定一个快照；ContextVar 的 finally 复位，线程和交错异步请求互不借用快照。',
              '- 文件签名包含 dev/inode/size/mtime_ns/ctime_ns。正常写入签名变化在下一请求立即加载；'
              '同 tick 原地改写且完整签名相同的极端情况，最长 30 秒后内容复核发现。损坏的相同版本在此期间不重复解析，恢复/原子替换能触发重载。',
              '- writer lock 串行准备，构建前后复核两个文件，最多重试两次，再以单个不可变对象发布。加载失败保留该 root/profile 的旧快照；'
              '没有旧快照时沿用 queryMusic 调用失败的命令结果。持续写入耗尽重试后，下一请求仍重试，不能永久封禁一个尚未验证的新版本。',
              '- 原子性指读者得到完整快照，不代表上游两个独立文件具备跨文件业务事务。revision 明确包含两份内容哈希；'
              '未更改上游公共数据发布协议，未增加磁盘 last-good 副本，进程重启后仍需要有效输入。', '',
              '## 复现与证据', '',
              '冻结目录只包含两份公共曲库，未提交歌曲资源。准备、主基线、完整验证分别执行：', '',
              '```bash',
              'QA=/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh',
              'PY=/opt/taiko-bot/releases/0.23.0/bin/python',
              'RUN=scripts/performance/song_query/run.py',
              'FIX=/var/tmp/taiko-song-query-replay/catalog',
              'OUT=/var/tmp/taiko-song-query-replay',
              'bash "$QA" "$PY" "$RUN" prepare --fixture "$FIX" --public /home/sigaer/taiko/songs',
              '# 必须先核对新曲库哈希；不同输入不能直接复现本报告数字。',
              '# 按 center / client 分别运行 baseline benchmark；client 需加 --core-source。',
              'bash "$QA" "$PY" "$RUN" benchmark --source /opt/taiko-bot/releases/0.23.0/lib/python3.11/site-packages \\',
              '  --fixture "$FIX" --profile center --output "$OUT/before-center.json" --repetitions 40',
              'bash "$QA" "$PY" "$RUN" benchmark --source /opt/taiko-bot/releases/0.23.0/lib/python3.11/site-packages \\',
              '  --fixture "$FIX" --profile client --core-source packages/sakura-taiko-core/core \\',
              '  --output "$OUT/before-client.json" --repetitions 40',
              'bash scripts/performance/song_query/verify.sh "$FIX" "$OUT"',
              '# REAL_QA / CENTER_QA / CLIENT_QA 填入本次测试输出的对应 QA run ID。',
              'bash "$QA" "$PY" scripts/performance/song_query/validate.py --work "$OUT" --source "$PWD" \\',
              '  --test-runs "$REAL_QA" "$CENTER_QA" "$CLIENT_QA"',
              'bash "$QA" "$PY" scripts/performance/song_query/report.py --work "$(dirname "$FIX")" \\',
              '  --output docs/performance/song-query/phase1',
              '```', '',
              '仓库内 before/after JSON 包含全部原始计时、CPU、阶段计数、实际命令返回和 QA run ID；'
              'trace 记录每轮 query 的 mode 与选项。QA vault manifest 保存退出和子进程清理状态；'
              '附加资源文件保存 cgroup 配额、memory.events 和进程最大 RSS。该内核不支持 memory.peak 时明确记为 null；'
              '早期主基线仅有进程最大 RSS，未记录 cgroup 峰值或 OOM 计数，不能据此声称 cgroup 峰值下降。'
              '测试结果和 QA 资源摘要见 [validation.json](validation.json)。', '',
              '静态谱面 Manifest 与官方 QQ Markdown URL 快速路径仍是下一阶段独立设计；'
              '本阶段未修改 QQ 全局发送、BXX 或动态图片缓存，也没有资源公开/HTTPS/QQ 兼容性的实施结论。', '']
    (args.output/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    (args.output/'artifacts.json').write_text(json.dumps(artifacts, indent=2)+'\n')
    print(json.dumps(dict(status='PASS', archived_files=len(artifacts), report=str(args.output/'report.md'))))


if __name__ == '__main__':
    main()
