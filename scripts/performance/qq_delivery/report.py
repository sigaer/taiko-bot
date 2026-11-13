from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from pathlib import Path
import statistics

from .config import MODES
from .state import atomic_json
from .transport import inventory


def stats(values):
    values = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v))
    if not values:
        return dict(n=0, p50_ms=None, p95_ms=None, min_ms=None, max_ms=None, p95_descriptive=True)
    return dict(n=len(values), p50_ms=round(statistics.median(values), 3),
                p95_ms=values[math.ceil(len(values) * .95) - 1], min_ms=values[0], max_ms=values[-1],
                p95_descriptive=len(values) < 20)


ROW_KEYS = {"sample", "mode", "phase", "status", "started_at", "finished_at", "total_ms",
            "image_sha256", "image_bytes", "calls", "observations", "transport", "auth_source", "ttl_seconds",
            "receipt_id_present", "upload_receipt_id_present", "active_quota_before", "active_quota_after",
            "error", "msg_seq", "url_access", "static_write_ms", "static_verify_ms", "jpeg_verified",
            "external_verification", "resolved"}
ROW_KEYS |= {"comparison_eligible", "cohort", "trigger_source"}


def export(folder: Path, state=None, *, environment=None, blockers=None):
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    rounds = {}
    if state is not None:
        for r in state.data["rows"]:
            rounds.setdefault(r["round_id"],len(rounds)+1)
            row=dict((k,r[k]) for k in sorted(ROW_KEYS) if k in r)
            row["round_index"]=rounds[r["round_id"]]
            rows.append(row)
    all_rows = rows
    rows = [r for r in all_rows if r.get("comparison_eligible", True)]
    excluded = [r for r in all_rows if not r.get("comparison_eligible", True)]
    summaries = []
    by_group = defaultdict(list)
    for row in rows:
        connection = next((c.get("connection_sample") for c in row["calls"] if c.get("connection_sample")), "unobservable")
        first_auth=row["calls"][0].get("access_token_changed") if row["calls"] else None
        key = (row["mode"], row["phase"], row["transport"], connection, row.get("url_access"),first_auth)
        by_group[key].append(row)
    for key, group in sorted(by_group.items(), key=lambda item: str(item[0])):
        ok = [r for r in group if r["status"] == "acknowledged"]
        attempted = [r for r in group if any(c.get("http_requests",0) for c in r["calls"])]
        observations = [o for r in group for o in r["observations"]]
        timings = defaultdict(list)
        for r in ok:
            for c in r["calls"]:
                timings[c["api"]].append(c["total_ms"])
                for name, duration in c["timings"].items():
                    timings[c["api"] + "." + name].append(duration)
                for span in c["http_trace"]:
                    timings[c["api"] + "." + span["phase"]].append(span["duration_ms"])
        quota_deltas = [r["active_quota_before"] - r["active_quota_after"] for r in group
                        if r["active_quota_before"] is not None and r["active_quota_after"] is not None]
        summaries.append(dict(mode=key[0], phase=key[1], transport=key[2], connection=key[3], url_access=key[4], first_api_token_changed=key[5],
            attempts=len(group), qq_api_attempted_samples=len(attempted), api_acknowledged=len(ok),
            api_success_rate=len(ok)/len(attempted) if attempted else None,
            client_observed_samples=sum(bool(r["observations"]) for r in group),
            client_received_samples=sum(any(o["received"] for o in r["observations"]) for r in group) if observations else None,
            client_receive_rate_over_observed_samples=sum(any(o["received"] for o in r["observations"]) for r in group)/sum(bool(r["observations"]) for r in group) if observations else None,
            operation_total=stats([r["total_ms"] for r in ok]),
            api_ack=stats([round(sum(c["total_ms"] for c in r["calls"]),3) for r in ok]),
            client_complete_by_device={device: stats([o.get("complete_ms") for o in observations if o["device"]==device]) for device in ("android", "windows")},
            client_start_by_device={device: stats([o.get("image_start_ms") for o in observations if o["device"]==device]) for device in ("android", "windows")},
            api_stage_timings={name:stats(values) for name,values in sorted(timings.items())},
            active_quota_consumed=sum(quota_deltas) if len(quota_deltas)==len(group) else None,
            active_potential_sends=sum(r["mode"].startswith("B") and any(c.get("http_requests",0) for c in r["calls"]) for r in group),
            message_send_http_requests=sum(c.get("http_requests",0) for r in group for c in r["calls"] if c.get("api")=="post_group_messages" or r["mode"].startswith("B")),
            total_qq_http_requests=sum(c.get("http_requests",0) for r in group for c in r["calls"]),
            errors=sum(r["status"]=="error" for r in group), unknown=sum(r["status"] in ("unknown","pending") for r in group),
            observed_duplicates=sum(max(o["duplicates"] for o in r["observations"]) for r in group if r["observations"])
                if observations and all(type(o.get("duplicates")) is int for o in observations) else None,
            timeout_but_received=sum(r["status"]=="unknown" and any(o["received"] for o in r["observations"]) for r in group) if observations else None,
            timeouts=sum(r.get("error",{}).get("category")=="timeout_or_network" for r in group if r.get("error"))))
    missing = [m for m in MODES if not any(s["mode"]==m for s in summaries)]
    result = dict(schema=1, generated_at=datetime.now(timezone.utc).isoformat(),
        status="no_live_samples" if not all_rows else "partial_observation",
        environment=environment or inventory(),
        boundary="operation_total includes static validation and bookkeeping; api_ack sums QQ API call intervals within each sample, excluding static preparation and gaps; client timing offsets are relative to sample started_at; later samples also retain per-call wall timestamps",
        capabilities=dict(active_send="not_verified" if not any(r["mode"].startswith("B") for r in rows) else "see_B_samples_and_manual_observations",
                          markdown="not_verified" if not any(r["mode"]=="C" for r in rows) else "see_C_samples_and_client_rendering",
                          quota="administrator_console_observations_required; no inferred balance"),
        blockers=blockers or [], missing_modes=missing, samples=all_rows, summaries=summaries,
        comparison_scope=dict(eligible_samples=len(rows), excluded_samples=len(excluded),
                              policy="Excluded API records remain in samples/errors but never enter comparison summaries."),
        active_quota_attestation={k: state.data.get("active_quota_attestation", {}).get(k)
                                  for k in ("remaining_lower_bound", "b_rows_count", "reported_at", "source")} if state else None,
        decision=dict(replace_current_two_stage_send="insufficient_evidence_keep_A",
                      faster_than_markdown="undetermined_without_matched_client_samples",
                      best_actual_receipt_time="undetermined_without_client_measurements",
                      release_new_strategy=False),
        limitations=["Server acknowledgements do not establish client image delivery.",
                     "Group by mode, payload path, transport, connection, phase and first/repeated URL.",
                     "No sum of phase medians; small-sample p95 is descriptive.",
                     "B has no separate content, quotes or keyboard; no automatic fallback or retry.",
                     "Synthetic public URLs do not establish suitability for private player images.",
                     "HTTP response-header wait is not an exact TTFB measurement; TCP includes DNS."])
    errors = [dict(sample=r["sample"], mode=r["mode"], status=r["status"], error=r.get("error"))
              for r in all_rows if r.get("error") or r["status"] in ("pending", "unknown")]
    atomic_json(folder / "qq-delivery-results.json", result)
    atomic_json(folder / "qq-delivery-errors.json", dict(schema=1, errors=errors, blockers=blockers or []))
    lines = ["# QQ 官方图片发送实验", "", "本报告由独立测试工具生成；生产 BXX 发送策略保持不变。", "",
             "## 环境与能力预检", "", "```json", __import__('json').dumps(result["environment"],ensure_ascii=False,indent=2), "```", "",
             "主动权限、群授权、file_data/url 平台支持、Markdown 白名单与额度须以真实预检及控制台记录为准。", "",
             "## 分组结果", "", "|模式|阶段/传输/连接/URL|尝试|API成功率|API调用合计 P50 ms|API调用合计 P95 ms|Android完整收图 P50 ms|", "|---|---|---:|---:|---:|---:|---:|"]
    for s in summaries:
        rate=f"{s['api_success_rate']:.1%}" if s['api_success_rate'] is not None else "未调用"
        lines.append(f"|{s['mode']}|{s['phase']}/{s['transport']}/{s['connection']}/{s['url_access']}|{s['attempts']}|{rate}|{s['api_ack']['p50_ms']}|{s['api_ack']['p95_ms']}|{s['client_complete_by_device']['android']['p50_ms']}|")
    if not rows:
        lines.append("|A-data / A-url / B-data / B-url / C / D|未进行真实发送|0|未测|未测|未测|未测|")
    lines += ["", f"对照统计纳入 {len(rows)} 条记录；另有 {len(excluded)} 条保留为审计证据，不纳入对照统计。",
              "samples 保留全部 API 事实；comparison_eligible、cohort 和 trigger_source 标明统计范围与操作来源。管理员报告的额度下限单独保存，不当作实际扣减量。",
              "API调用合计为每条样本内QQ API调用完整耗时之和，排除静态URL验证和调用间隙；包含准备与持久化的整步耗时另见 operation_total。",
              "每模式成功率、最小/最大值、完整 API 子阶段、Windows 观察、重复发送、未知结果及主动额度见同目录 JSON。",
              "未观察客户端或控制台额度的字段为 null，不以0代替。少于20个样本的 P95 只作描述。", "",
              "## 阻塞条件", ""] + [f"- {b}" for b in (blockers or ["无工具前置阻塞；仍需逐项完成真实群测试和客户端观察。"]) ]
    lines += ["", "## 生产决策", "", "证据不足时保持 A。当前不能证明主动上传即发送可以替代两阶段发送，不能判断它比 Markdown 更快，也不能确定实际收图最快的方案。",
              "即使后续获得较低 API 延迟，仍需核对客户端完整加载、重复消息、主动额度、Markdown 渲染、文字/引用/按钮差异及隐私。",
              "B 仅发送图片；C 测试资源为短时公开合成图片，这不构成发布私人 BXX 的许可。D 仅复用本 Bot、本测试群、同一合成图的有效媒体凭据。",
              "工具不会自动推荐发布或切换策略；正式试点需达到至少约20%的可重复 P50 优势，P95不恶化并完成全部兼容性验收。", ""]
    (folder / "qq-delivery-comparison.md").write_text("\n".join(lines))
    return result
