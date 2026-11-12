"""Assemble raw before/after evidence and a numerical, reproducible release report."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

COHORTS=['warm-query','warm-compute','warm-draw','cold','matrix-center','matrix-client','edges-center','edges-client','handler']
MAIN=[('U05','taikob30 v1'),('U05','taikob'),('U08','taikob30 v1'),('U08','taikob'),('U11','taikob'),('U12','taikob')]


def stats(values):
    values=sorted(values)
    return dict(n=len(values),p50=statistics.median(values),p95=values[math.ceil(len(values)*.95)-1],mean=statistics.mean(values),min=values[0],max=values[-1])


def summary(rows):
    grouped=defaultdict(list)
    for row in rows:grouped[(row['profile'],row['user'],row['command'],row['scope'])].append(row)
    result=[]
    for key,group in grouped.items():
        result.append(dict(zip(('profile','user','command','scope'),key))|dict(
            wall_ns=stats([r['wall_ns'] for r in group]),cpu_ns=stats([r['cpu_ns'] for r in group]),
            peak_rss_kib=stats([r['peak_rss_kib'] for r in group]),
            sequential_rps=1e9/statistics.mean(r['wall_ns'] for r in group)))
    return result


def load(root,label):
    cohorts={name:[json.loads(l) for l in (root/f"{label+'-confirmed' if label=='before' and name in COHORTS[:4] else label}-{name}.jsonl").read_text().splitlines()] for name in COHORTS}
    assert [len(cohorts[c]) for c in COHORTS]==[120,120,120,30,182,112,28,20,80]
    stress={name:json.loads((root/f'{label}-{name}.json').read_text()) for name in ['memory','concurrency']}
    assert all(r['status']=='PASS' for r in stress.values())
    return dict(schema='taiko-b30-performance-v1',variant=label,
        release=dict(bot='0.21.1' if label=='before' else '0.21.2',application='0.8.2' if label=='before' else '0.8.3'),
        measurement=dict(clock='perf_counter_ns',cpu='process_time_ns',warmup=3,repeats=20,cold_processes_per_case=5,
                         p95='nearest rank',peak_rss='process high watermark in KiB, cumulative within each process'),
        cohorts=cohorts,stress=stress,summary={k:summary(v) for k,v in cohorts.items()})


def validate(before,after):
    counts=defaultdict(int)
    for cohort in ['matrix-center','matrix-client','edges-center','edges-client']:
        for old,new in zip(before['cohorts'][cohort],after['cohorts'][cohort]):
            key=(old['profile'],old['user'],old['command'])
            assert key==(new['profile'],new['user'],new['command'])
            assert old['output']==new['output'],(key,'final output')
            counts['commands']+=1
            if old['output'].get('kind')=='image':counts['jpeg']+=1
            x,y=old['artifacts'],new['artifacts']
            for field in ['all_results','summary_algorithm']:
                assert x.get(field)==y.get(field),(key,field)
                if field in x:counts[field]+=1
            png=x.get('default_png') or (x.get('encoder_input') if 'sha256' in x.get('encoder_input',{}) else None)
            if png:
                assert png==y.get('default_png'),(key,'default PNG API')
                counts['png']+=1
            if 'encoder_input' in x:
                for field in ['size','pixels','rgb_pixels']:
                    assert x['encoder_input'][field]==y['encoder_input'][field],(key,'encoder RGB',field)
                counts['encoder_pixels']+=1
    for cohort in ['warm-query','warm-compute','warm-draw','cold','handler']:
        assert [(r['user'],r['command'],r['output']) for r in before['cohorts'][cohort]]==[(r['user'],r['command'],r['output']) for r in after['cohorts'][cohort]],cohort
    return dict(status='PASS',**counts)


def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--code-commit',required=True);p.add_argument('--deployment',type=Path,required=True);a=p.parse_args()
    root=a.work/'results';a.output.mkdir(parents=True,exist_ok=True)
    before=load(root,'before');after=load(root,'after');correct=validate(before,after)
    manifest=json.loads((a.work/'fixture/fixture-manifest.json').read_text());edge=json.loads((a.work/'fixture/edge-fixture-manifest.json').read_text())
    provenance=dict(baseline_commit='cf66562d11128dad7c327d49ad665a45a2684eaf',optimized_commit=a.code_commit,
        fixture_manifest_sha256=hashlib.sha256((a.work/'fixture/fixture-manifest.json').read_bytes()).hexdigest(),
        fixtures=manifest,extra_fixtures=edge,system_fonts=(root/'system-fonts.sha256').read_text(),
        dependencies=json.loads((root/'dependency-parity.json').read_text()),
        baseline_freeze=(root/'production-freeze.txt').read_text())
    for data in [before,after]:
        data['provenance']=provenance
        (a.output/f"benchmark-{data['variant']}.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    parity=json.loads((a.work/'phase2b-installed/parity.json').read_text());assert parity['status']=='PASS'
    authority={name:json.loads((a.work/f'host-{name}/host-events.json').read_text()) for name in ['center','client']}
    assert all(x['status']=='PASS' for x in authority.values())
    deployment=json.loads(a.deployment.read_text())
    lines=['# B30 全链路性能报告：Taiko Bot 0.21.2','',
      f'代码基线：Bot 0.21.1 / Application 0.8.2，`{provenance["baseline_commit"]}`。优化：Bot 0.21.2 / Application 0.8.3，`{a.code_commit}`。核实 main 和生产均已超过原建议的 0.20.2，因此发布 0.21.2。',
      '', '所有数字来自本次原始测量；旧耗时 / 新耗时为加速倍数。原始纳秒计时、独占/累计阶段、CPU、RSS、尺寸、字节数、哈希和环境逐条保存在同目录两份 JSON。',
      '', '## 环境、样本与范围','',
      'Intel Xeon Platinum 8255C 2.50GHz，宿主 8 vCPU / 31 GiB RAM；所有测量使用现有 QA 隔离器：CPUQuota=200%，MemoryHigh=2 GiB，MemoryMax=3 GiB，SwapMax=256 MiB，每项最长 15 分钟。未清理宿主文件缓存，未提高生产资源限制。各进程负载和 cgroup 配额保留于原始 environment。',
      '', 'Python 3.11.4、Pillow 11.3.0、NumPy 2.4.6、Pandas 3.0.6，中心 Core 0.1.1 / Contract 0.1.0。客户端使用独立的已安装 Core 0.1.2 模块覆盖，保持相同 Python/Pillow。除 Bot/Application 外，115 个依赖、8667 个安装文件的版本及内容与旧发布逐一一致。没有以依赖升级换取性能。',
      '', '固定种子 20261112、时刻 2026-11-11T12:00:00；冻结公共曲库、V2 CSV、字体和 6591 个相关资源文件。完整修订及资源 SHA256 位于 JSON 的 provenance。成绩、历史、绑定均为合成；没有读取其他玩家私有数据。固定输入保存在隔离目录，未提交任何玩家文件或资源包。',
      '', '|样本|覆盖|成绩数|历史快照数|','|---|---|---:|---:|']
    for u in manifest['users']:lines.append(f"|{u['id']}|{u['description']}|{u['records']}|{u['snapshots']}|")
    lines += ['', 'U09 包含重复谱面与旧版本 ID；U13 包含两个合成账号的 u0 合并；U14 使用实际公共多语言长曲名和合成装扮。额外 E01 仅 easy/normal/hard、E02 五难度混合、E03 全部低于 75% 精度，验证无可计分结果和非鬼谱语义。',
      '', '中心端每个 U 样本覆盖 13 条命令：`taikob`、`taikob20 v2`、`taikob30 v2`、`taikob20 v1`、`taikob30 v1`、`taikob50 v1`、`taikob20 v2 精度`、`taikob30 v1 精度`、`taikob20 v2 体力`、`taikob20 v1 节奏`，以及 nonsense、-r、v1/v2 冲突。客户端每个 U 覆盖 `taikob20/30/50`、`taikob20 v2`、v2 精度/体力、非法 v2 Top30、非法维度；另有 48 个尺寸、维度别名、缺参、版本、空结果边界。完整命令逐条保存在 JSON。',
      '', '中心默认 `taikob` 保持 v2 Top20，原版已不经过完整 v1 计算；客户端默认仍为 v1，v2 仅支持 Top20，其布局、重复版本策略和错误提示均保留。`taikob30 v1` 经 Application execute → 中心 B30 adapter → Application B30Renderer → 30 张 Single 卡片。客户端经自身 legacy renderer。',
      '', '## 测量口径','',
      '六个主要场景各新进程 5 次；热缓存预热 3 次、正式 20 次。query 包括真实 PublicationStore 当前/历史对象读取、完整性验证、历史重建、计算和生产 JPEG 路径；身份为固定模拟端口。compute 使用预先读取的输入，每次仍新建请求级私人计算缓存；draw 使用固定 ScoreContext，测默认 PNG API 绘图及原编码包装，便于比较 API 本身。网络、平台发送和远端 SQL 延迟均不计入。',
      '', '另以真实 NoneBot Matcher/Provider、只读合成 SQL authority 和真实 PublicationStore 测量完整 handler（4 个场景各 3+20 次）；包含授权算法及发送前复核，发送端仅记录图像哈希。没有通过真实 Bot 账号制造流量。',
      '', '阶段 A–F 使用 perf_counter_ns，保留父子关系。inclusive 为含子阶段累计值，exclusive 为扣除直接子阶段后的独占值，不能把各层 inclusive 相加。CPU 为 process_time_ns；峰值 RSS 为进程累计高水位，不能当作每请求净分配。P95 使用 nearest-rank。冷进程 query 表示新 Python 进程内首个查询，导入 startup 和外部进程总时长另存，后者还含隔离 fixture 初始化。',
      '', '## 热缓存完整查询（秒）','', '|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|','|---|---:|---:|---:|---:|---:|---:|']
    def values(data,cohort,key,field='wall_ns'):
        return [r[field] for r in data['cohorts'][cohort] if (r['user'],r['command'])==key]
    def formatted_table(cohort,keys=MAIN):
        rows=[]
        for key in keys:
            old=stats(values(before,cohort,key));new=stats(values(after,cohort,key));factor=old['p50']/new['p50']
            rows.append(f'|{key[0]} {key[1]}|{old["p50"]/1e9:.3f}|{new["p50"]/1e9:.3f}|{old["p95"]/1e9:.3f}|{new["p95"]/1e9:.3f}|{factor:.2f}×|{(1-1/factor)*100:.1f}%|')
        return rows
    lines+=formatted_table('warm-query')
    for cohort,title in [('warm-compute','已准备数据后的完整计算与生产绘图'),('warm-draw','纯绘图：默认 PNG API 与编码'),('cold','冷进程内首个完整查询'),('handler','真实 Matcher 完整链路')]:
        lines+=['',f'## {title}（秒）','', '|样本/命令|旧 P50|新 P50|旧 P95|新 P95|P50 加速|降幅|','|---|---:|---:|---:|---:|---:|---:|']+formatted_table(cohort,MAIN if cohort!='handler' else [MAIN[0],MAIN[1],MAIN[3],MAIN[5]])
    lines+=['','## CPU、内存和输出','', '|样本/命令|旧 CPU P50 秒|新 CPU P50 秒|旧峰值 RSS MiB|新峰值 RSS MiB|尺寸|JPEG 字节|','|---|---:|---:|---:|---:|---|---:|']
    for key in MAIN:
        o=next(r for r in before['cohorts']['warm-query'] if (r['user'],r['command'])==key);n=next(r for r in after['cohorts']['warm-query'] if (r['user'],r['command'])==key)
        out=n['output'];size=out.get('size',out.get('dimensions','见原始数据'));byte=out.get('bytes',out.get('byte_count',0))
        lines.append(f'|{key[0]} {key[1]}|{statistics.median(values(before,"warm-query",key,"cpu_ns"))/1e9:.3f}|{statistics.median(values(after,"warm-query",key,"cpu_ns"))/1e9:.3f}|{max(values(before,"warm-query",key,"peak_rss_kib"))/1024:.1f}|{max(values(after,"warm-query",key,"peak_rss_kib"))/1024:.1f}|{size}|{byte}|')
    lines+=['','## 分项优化及局部复测','', '每步以相同六场景执行一次未预热的隔离查询。以下为实测毫秒及相对前一步倍数，仅用于定位来源，单次采样受冷资源和负载影响，正式结论以上方 20 次分布为准。历史聚合的最后一轮是在有界执行器接入后补测，未伪装成早期测量。', '', '|步骤|标准 v1|默认 v2|密集 v1|密集 v2|30 天历史|180 天历史|','|---|---:|---:|---:|---:|---:|---:|']
    steps=[('native-smoke','旧版'),('step1-direct-card','单卡直接 Image'),('step2-rating','同参数 Rating 复用'),('step3-resources','共享字体模板与封面'),('step4-jpeg','最终 JPEG 直出'),('step5-catalog','公共曲库及索引'),('step5b-revisions','修订失效完善'),('step6-history','历史窗口重建'),('step6b-dimensions','v2/维度图资源'),('step7-pillow','相同尺寸 resize 消除'),('step8-pure-boundary','纯计算线程边界'),('step6c-aggregation','相同输入历史六维复用')]
    previous=None;local=[]
    for filename,title in steps:
        rows=[json.loads(l) for l in (root/f'{filename}.jsonl').read_text().splitlines()];mapping={(r['user'],r['command']):r for r in rows};current=[mapping[k]['wall_ns'] for k in MAIN]
        line=[title]+[f'{v/1e6:.1f}'+(f' ({previous[i]/v:.2f}×)' if previous else '') for i,v in enumerate(current)]
        lines.append('|'+'|'.join(line)+'|');local.append(dict(step=title,records=rows));previous=current
    (a.output/'optimization-steps.json').write_text(json.dumps(local,ensure_ascii=False,indent=2)+'\n')
    lines+=['', '单卡不再做 30 次 PNG 编码/解码，使用相同 LANCZOS 与尺寸。请求级共享只读资源、先复制模板再写玩家内容；跨请求仅缓存公共图片，限额 64 MiB。字体请求限额 128、私人 Rating memo 32 项/32000 行、同输入聚合 64 项；不缓存最终私人图片。',
      '', 'v1 预计算仅在评分 profile、去重策略、用户、完整有序成绩摘要与曲库修订相同才复用。v2 使用自身结果；删除重复全量计算前保留了无可计分结果的旧判定语义。历史只保留需要的最近窗口，仍按原完整+增量序列重放；相同快照 Rating/六维在请求内复用，未启用跨玩家私人历史缓存，未改变每日归档行为。',
      '', '公共 JSON/Rating/index/重复版本/V2 CSV 按路径、mtime_ns、size、inode、ctime 修订失效。测试发现宿主 4ms 时间戳粒度可能让快速同尺寸写入别名，修复为新近文件校验内容摘要、图片新近更新暂不跨请求缓存；相关失败测试修复后原断言全部通过。没有降低图像质量或修改评分公式。',
      '', 'Pillow 操作仅删除可证明相同的操作；标题截断、布局搜索、雷达图和非等尺寸缩放保留原算法与滤镜。Matplotlib 分支保留主线程并占用相同并发预算，避免 pyplot 线程不安全；其本身仍可能短暂阻塞事件循环。局部步骤出现单次噪声/无收益时没有把其标成稳定加速；收益主要来自资源复用与编码消除。',
      '', '## 图片、算法及授权验收','',f'命令矩阵与扩展边界共 {correct["commands"]} 项，输出全部与旧版一致。{correct["all_results"]} 项全量 Rating 结果摘要、{correct["summary_algorithm"]} 项 TopN/综合/六维/趋势/历史差异/NEW 计算摘要一致；{correct["png"]} 项默认 PNG 字节 SHA256 与解码像素一致；{correct["encoder_pixels"]} 项生产编码前 RGB/原始像素与尺寸一致。最终 JPEG 字节、尺寸、像素和长度均一致（quality=85、optimize=True，透明区域原白底处理）。',
      '',f'原 Application Phase 2B 的 {len(parity["cases"])} 项图片/缺资源用例全部通过；使用原 provenance 与哈希，没有更新 golden 来适应新输出。安装包 standalone 4 项通过。中心/客户端真实 Matcher 各 {len(authority["center"]["cases"])} 项，覆盖 OneBot/QQ、普通/u0、准备后/渲染后/发送时撤权、成员/顺序/当前档案变更及解绑，SQL 与 PublicationStore lease 均留在主线程，无真实发送。',
      '', '主回归 44 项、客户端 V2/可见性 7 项、已安装 wheel cache smoke 4 项均通过。执行器另测限额、队列拒绝、取消、超时、异常及启动关闭；取消后协作停止，实际工作结束前不归还占用，最多 2 个绘图和 1 个等待请求。',
      '', '## 并发与资源生命周期','', '|并发|旧请求 P50/P95 秒|新请求 P50/P95 秒|P95 加速|旧/新吞吐 req/s|旧/新事件循环最大间隔 秒|','|---:|---|---|---:|---|---|']
    for concurrency in [2,3]:
        os=[r for r in before['stress']['concurrency']['batches'] if r['concurrency']==concurrency];ns=[r for r in after['stress']['concurrency']['batches'] if r['concurrency']==concurrency]
        ov=stats([v for r in os for v in r['request_wall_ns']]);nv=stats([v for r in ns for v in r['request_wall_ns']])
        throughput=lambda rows:len(rows)*concurrency*1e9/sum(r['wall_ns'] for r in rows)
        lines.append(f'|{concurrency}|{ov["p50"]/1e9:.3f} / {ov["p95"]/1e9:.3f}|{nv["p50"]/1e9:.3f} / {nv["p95"]/1e9:.3f}|{ov["p95"]/nv["p95"]:.2f}×|{throughput(os):.3f} / {throughput(ns):.3f}|{max(r["max_event_loop_gap_ns"] for r in os)/1e9:.3f} / {max(r["max_event_loop_gap_ns"] for r in ns)/1e9:.3f}|')
    lines+=['', '每档 20 批，混合 v1/v2 与长期历史。三请求包含等待时间；旧版同步串行，新版两个 worker，不把线程池收益算作单次算法提速。', '', '|版本|预热 RSS MiB|第50次|第100次|轮换14用户至128次|公共缓存 MiB/上限|','|---|---:|---:|---:|---:|---|']
    for data in [before,after]:
        m=data['stress']['memory'];rss={r['iteration']:r['rss_kib']/1024 for r in m['rss']};cache=m['cache'];cachetext=f'{cache["bytes"]/1048576:.2f} / {cache["limit"]/1048576:.0f}' if isinstance(cache,dict) else '无进程图片缓存'
        lines.append(f'|{data["variant"]}|{rss[0]:.1f}|{rss[50]:.1f}|{rss[100]:.1f}|{rss[128]:.1f}|{cachetext}|')
    lines+=['', '连续同用户100次、不同用户轮换28次与混合并发均完成，无 OOM；逐次原始 RSS、耗时及周期采样在 JSON 中。三次实际第三卡异常验证所有请求拥有的 Pillow 图片关闭，后续请求恢复；新执行器重复完整启动/关闭3次，最终无 active/admitted。资源缓存有界且失效测试通过。',
      '', '## 阶段证据（热查询均值毫秒）','', '|场景/阶段|旧累计|新累计|旧独占|新独占|','|---|---:|---:|---:|---:|']
    for key in MAIN[:2]:
        old=[r for r in before['cohorts']['warm-query'] if (r['user'],r['command'])==key];new=[r for r in after['cohorts']['warm-query'] if (r['user'],r['command'])==key]
        names=sorted(set().union(*(r['stages'] for r in old+new)))
        for name in names:
            vals=[statistics.mean(r['stages'].get(name,{}).get(field,0) for r in group)/1e6 for field in ['inclusive_ns','exclusive_ns'] for group in [old,new]]
            if max(vals)<5:continue
            lines.append(f'|{key[1]} / {name}|'+ '|'.join(f'{v:.2f}' for v in vals)+'|')
    lines+=['', '## 发布与剩余瓶颈','', '安装包版本和物理模块路径由生产进程启动日志中的 runtime inventory 核对。发布仅切换 taiko-bot.service，不重启 Viewer、同步接收器或其他游戏。原运行架构只有 37564 监听，37563 在基线即无监听；保持实际端口和既有连接方式，没有为迁就旧架构描述额外创建服务。', '', '部署证据：', '', '```json',json.dumps(deployment,ensure_ascii=False,indent=2),'```','',
      '旧 `/opt/taiko-bot/releases/0.21.1`、原依赖包及代码基线保留。回滚：`TAIKO_DEPLOY_BOT_ONLY=1 scripts/deploy_taiko.sh 0.21.1 0`。源代码与安装包发布来自本报告代码提交；报告自身的后续提交不改变已验收 wheel。',
      '', '剩余主要耗时为固定布局的文字/卡片合成、JPEG 编码及长期历史真实重建；密集成绩排序/Rating 仍遵守原算法。冷进程导入、系统字体初始化及文件系统读取不能由热缓存收益代替。网络、真实远端 SQL 和平台传输不在离线数字中；真实 handler 已验证本地算法/授权边界。没有改变生产玩家数据、授权、绑定、每日历史档案或其他服务。',
      '', '复现：先用 fixtures.py 固定公共资源与合成输入；通过现有 run_qa.sh 分别以旧/新已安装解释器运行 run_cohorts.py、stress.py 和 host_events.py。每次使用相同冻结 fixture，完整命令与实施脚本位于 scripts/performance。测试及构建原始日志保留在 /home/sigaer/taiko/qa-vault/runs，隔离输入和步骤证据保留在 /var/tmp/taiko-b30-performance。','']
    (a.output/'b30-performance-report.md').write_text('\n'.join(lines))
    (a.output/'correctness.json').write_text(json.dumps(correct,indent=2)+'\n')
    print(correct)


if __name__=='__main__':main()
