from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import time

from .config import Blocked, MODES
from .events import validate_trigger
from .images import StaticImage, image_payload
from .state import State
from .transport import ApiFailure, Transport


class Experiment:
    def __init__(self, config, bot=None, *, connected=True):
        self.config, self.bot, self.connected = config, bot, connected

    async def run(self, mode, event=None, *, live=False, active_trial=False):
        if mode not in MODES:
            raise Blocked("invalid_mode")
        if not live:
            return dict(status="dry_run", mode=mode, real_api_calls=0,
                        required="private config + explicit --live + fresh authorized group event")
        c = self.config
        c.validate_live()
        if active_trial:
            if not mode.startswith("B") or c.phase != "protocol":
                raise Blocked("active_trial_only_for_B_protocol")
        else:
            validate_trigger(c, event, active_protocol=mode.startswith("B") and c.phase == "protocol")
        if self.bot is None or str(self.bot.self_id) != c.bot_id:
            raise Blocked("selected_bot_not_available")
        with State(c).locked() as state:
            if active_trial and any(r["mode"]==mode for r in state.data["rows"]):
                raise Blocked("active_protocol_trial_already_reserved")
            b_rows = [r for r in state.data["rows"] if r["mode"].startswith("B")]
            if mode.startswith("B"):
                if c.active_permission is False or c.group_active_allowed is False:
                    raise Blocked("active_permission_denied")
                if any(m.startswith("B") for m in state.data["blocked_modes"]):
                    raise Blocked("active_mode_stopped_requires_manual_review")
                if c.phase == "performance":
                    snapshots=[i for i,r in enumerate(b_rows) if r["active_quota_after"] is not None]
                    remaining=(b_rows[snapshots[-1]]["active_quota_after"]-len(b_rows[snapshots[-1]+1:])) if snapshots else 0
                    if not c.active_performance_authorized or remaining<=0:
                        raise Blocked("active_performance_permission_and_quota_required")
            elif not b_rows and c.active_permission is not False and c.group_active_allowed is not False:
                raise Blocked("single_active_protocol_preflight_required_first")
            if mode == "C" and not c.markdown_authorized:
                raise Blocked("markdown_permission_not_confirmed")
            if mode == "D":
                media = state.data.get("media")
                if not media or media["expires_at"] <= time.time() + 5:
                    raise Blocked("media_ttl_missing_or_expired_no_automatic_upload")
            # One locally generated image is reused; never accept production images.
            data = image_payload(state.directory)
            digest = hashlib.sha256(data).hexdigest()
            if mode == "D" and state.data["media"]["image_sha256"] != digest:
                raise Blocked("media_image_mismatch")
            # An explicit active-only operator action is not a passive QQ event.
            # This private reservation key is never sent as msg_id/event_id.
            reservation = "active-protocol-trial:"+mode if active_trial else event.message_id
            row = state.reserve(mode, reservation, digest)
            row["image_bytes"] = len(data)
            row["auth_source"] = "connected_bot" if self.connected else "isolated_bot_existing_config"
            row["msg_seq"] = None if mode.startswith("B") else 1
            row["url_access"] = None
            transport = Transport(self.bot, c, connected=self.connected)
            start = time.perf_counter()
            send_possible = False

            async def call(api, arguments, *, sends):
                nonlocal send_possible
                send_possible |= sends
                record = {}
                row["calls"].append(record)
                state.save()
                return await transport.call(api, arguments, record, state.save)

            try:
                url = None
                if mode in ("A-url", "B-url", "C"):
                    written = time.perf_counter()
                    static = StaticImage(c)
                    url, cached = static.prepare(data, state)
                    row["static_write_ms"] = round((time.perf_counter() - written) * 1000, 3)
                    row["url_access"] = "repeated_url" if cached else "first_url"
                    row.update(await static.verify(url, data))
                kwargs = dict(group_openid=c.group_openid, file_type=1,
                              srv_send_msg=mode.startswith("B"))
                if mode.endswith("-data"):
                    kwargs["file_data"] = data
                elif mode.endswith("-url"):
                    kwargs["url"] = url
                if mode.startswith(("A", "B")):
                    upload_started_at = time.time()
                    uploaded = await call("post_group_files", kwargs, sends=mode.startswith("B"))
                    ttl = getattr(uploaded, "ttl", None)
                    row["ttl_seconds"] = ttl if type(ttl) is int else None
                    row["upload_receipt_id_present"] = bool(transport.raw and transport.raw.get("id"))
                    if mode.startswith("B"):
                        row["receipt_id_present"] = row["upload_receipt_id_present"]
                    else:
                        if not uploaded.file_info:
                            raise ApiFailure("missing_media_credential")
                        from nonebot.adapters.qq.models import Media
                        receipt = await call("post_group_messages", dict(group_openid=c.group_openid,
                            msg_type=7, content=" ", media=Media(file_info=uploaded.file_info),
                            msg_id=event.message_id, msg_seq=1), sends=True)
                        row["receipt_id_present"] = bool(receipt.id)
                        if row["receipt_id_present"] and type(ttl) is int and ttl >= 0:
                            # ttl=0 is documented unlimited; keep this experiment's
                            # own private credential lease bounded to 30 minutes.
                            state.data["media"] = dict(file_info=uploaded.file_info,
                                image_sha256=digest, expires_at=upload_started_at + min(ttl or 1800, 1800),
                                ttl_reported=ttl, uploaded_by_sample=row["sample"])
                elif mode == "C":
                    from nonebot.adapters.qq.models import MessageMarkdown
                    markdown = f"QQ synthetic delivery test\n![img#1080px #2436px]({url})\nSynthetic feedback text."
                    receipt = await call("post_group_messages", dict(group_openid=c.group_openid,
                        msg_type=2, markdown=MessageMarkdown(content=markdown),
                        msg_id=event.message_id, msg_seq=1), sends=True)
                    row["receipt_id_present"] = bool(receipt.id)
                else:
                    from nonebot.adapters.qq.models import Media
                    media = state.data["media"]
                    row["ttl_seconds"] = max(0, int(media["expires_at"] - time.time()))
                    receipt = await call("post_group_messages", dict(group_openid=c.group_openid,
                        msg_type=7, content=" ", media=Media(file_info=media["file_info"]),
                        msg_id=event.message_id, msg_seq=1), sends=True)
                    row["receipt_id_present"] = bool(receipt.id)
                row["status"] = "acknowledged"
            except Blocked as error:
                row["status"] = "blocked_before_send"
                row["error"] = dict(category=str(error), code=None, http_status=error.http_status, result_unknown=False)
            except ApiFailure as error:
                row["status"] = "unknown" if error.unknown and send_possible else "error"
                row["error"] = error.public()
                state.data["blocked_modes"].append(mode)
                if mode.startswith("B"):
                    state.data["blocked_modes"].extend(["B-data", "B-url"])
                if mode == "D":
                    state.data["media"] = None
            except BaseException as error:
                row["status"] = "unknown" if send_possible else "interrupted_before_send"
                row["error"] = dict(category="interrupted" if isinstance(error, asyncio.CancelledError) else "local_error",
                                    code=None, http_status=None, result_unknown=send_possible)
                state.data["blocked_modes"].append(mode)
                if not isinstance(error, Exception):
                    raise
            finally:
                row["total_ms"] = round((time.perf_counter() - start) * 1000, 3)
                row["finished_at"] = time.time()
                state.data["last_finished"] = row["finished_at"]
                state.save()
            # Only a sample reference and category leave the private journal.
            return dict(sample=row["sample"], mode=mode, status=row["status"],
                        total_ms=row["total_ms"], error=row["error"])
