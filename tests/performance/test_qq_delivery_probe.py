"""Use the production installed SDK with synthetic responses; never contact QQ."""
import asyncio
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/performance"))

from qq_delivery.config import Blocked, Config
from qq_delivery.events import Trigger, journal_trigger
from qq_delivery.experiment import Experiment
from qq_delivery.images import StaticImage, cleanup_static, synthetic_jpeg
from qq_delivery.report import export, stats
from qq_delivery.state import State
from qq_delivery.transport import HttpTrace, inventory
from qq_delivery_probe import main, observe


class FakeAdapter:
    def __init__(self):
        self.requests = []
        self.responses = []

    def get_api_base(self):
        from nonebot.drivers import URL
        return URL("https://api.bot.qq.com/")

    async def request(self, setup):
        from nonebot.drivers import Response
        self.requests.append(setup)
        if self.responses:
            result = self.responses.pop(0)
            if isinstance(result, BaseException):
                raise result
            status, body = result
        elif str(setup.url).endswith("/files"):
            status, body = 200, dict(file_info="SECRET_FILE_INFO", ttl=600, id="SECRET_ACTIVE_ID")
        else:
            status, body = 200, dict(id="SECRET_MESSAGE_ID")
        return Response(status, content=json.dumps(body).encode(), request=setup)


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jpeg = synthetic_jpeg()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.c = Config(bot_id="SECRET_BOT", group_openid="SECRET_GROUP", admin_openids=["SECRET_ADMIN"],
                        active_test_authorized=True, max_sends_per_round=3, private_dir=str(self.root / "private"))
        self.adapter = FakeAdapter()
        self.bot = SimpleNamespace(self_id=self.c.bot_id, adapter=self.adapter, _access_token="SECRET_TOKEN",
                                   get_authorization_header=AsyncMock(return_value={"Authorization":"QQBot SECRET_TOKEN"}))
        self.image_patch = patch("qq_delivery.experiment.image_payload", return_value=self.jpeg)
        self.image_patch.start()

    def tearDown(self):
        self.image_patch.stop()
        self.tmp.cleanup()

    def event(self, n=0):
        return Trigger(self.c.bot_id, self.c.group_openid, self.c.admin_openids[0], f"SECRET_EVENT_{n}", time.time())

    def run_mode(self, mode="B-data", n=0, config=None):
        return asyncio.run(Experiment(config or self.c, self.bot).run(mode, self.event(n), live=True))

    def reset_interval(self):
        with State(self.c).locked() as s:
            s.data["last_finished"] = 0
            s.save()

    def test_inventory_uses_installed_api_signatures(self):
        env = inventory()
        self.assertIn("file_data", env["post_group_files"])
        self.assertIn("msg_seq", env["post_group_messages"])
        self.assertRegex(env["packages"]["taiko-bot"], r"^\d+\.\d+\.\d+")

    def test_synthetic_jpeg_dimensions_size_and_no_metadata(self):
        from PIL import Image
        with Image.open(BytesIO(self.jpeg)) as img:
            self.assertEqual(img.size, (1080,2436))
            self.assertEqual(img.format,"JPEG")
            self.assertFalse(img.getexif())
        self.assertTrue(500*1024 <= len(self.jpeg) <= 800*1024)

    def test_default_dry_run_does_not_construct_bot_or_call_api(self):
        with patch("qq_delivery_probe.standalone_bot",side_effect=AssertionError("network forbidden")):
            result = asyncio.run(Experiment(Config()).run("B-data"))
            self.assertEqual(result["real_api_calls"],0)
            self.assertEqual(main(["--output",str(self.root/"report"),"run"]),0)
        self.assertFalse(self.adapter.requests)

    def test_missing_each_mandatory_condition_blocks_all_network(self):
        for kwargs in [dict(bot_id=""),dict(group_openid=""),dict(active_test_authorized=False),
                       dict(max_sends_per_round=0),dict(admin_openids=[]),dict(interval_seconds=1)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(Blocked):
                self.run_mode(config=replace(self.c,**kwargs))
        self.assertFalse(self.adapter.requests)

    def test_private_config_permissions_and_schema(self):
        path=self.root/"config.json"
        path.write_text(json.dumps(vars(self.c)))
        path.chmod(0o644)
        with self.assertRaises(Blocked):Config.load(path)
        path.chmod(0o600)
        self.assertEqual(Config.load(path).bot_id,self.c.bot_id)
        alias=self.root/"alias.json";alias.symlink_to(path)
        with self.assertRaises(Blocked):Config.load(alias)

    def test_group_bot_admin_and_stale_event_are_rejected(self):
        bad=[replace(self.event(),bot_id="other"),replace(self.event(),group_openid="other"),
             replace(self.event(),admin_openid="other"),replace(self.event(),received_at=time.time()-4000)]
        for event in bad:
            with self.assertRaises(Blocked):
                asyncio.run(Experiment(self.c,self.bot).run("B-data",event,live=True))
        self.assertFalse(self.adapter.requests)

    def test_B_is_one_upload_without_passive_id_or_second_message(self):
        result=self.run_mode()
        self.assertEqual(result["status"],"acknowledged")
        self.assertEqual(len(self.adapter.requests),1)
        payload=self.adapter.requests[0].json
        self.assertTrue(payload["srv_send_msg"])
        self.assertIn("file_data",payload)
        self.assertNotIn("msg_id",payload)
        self.assertNotIn("content",payload)
        with State(self.c).locked() as s:
            self.assertTrue(s.data["rows"][0]["receipt_id_present"])

    def test_explicit_active_trial_needs_no_passive_event_and_is_once_per_mode(self):
        experiment=Experiment(self.c,self.bot)
        result=asyncio.run(experiment.run("B-data",live=True,active_trial=True))
        self.assertEqual(result["status"],"acknowledged")
        self.assertNotIn("msg_id",self.adapter.requests[0].json)
        self.reset_interval()
        with self.assertRaises(Blocked):asyncio.run(experiment.run("B-data",live=True,active_trial=True))
        with self.assertRaises(Blocked):asyncio.run(experiment.run("A-data",live=True,active_trial=True))
        self.assertEqual(len(self.adapter.requests),1)

    def test_url_and_markdown_payloads_do_not_silently_fall_back_to_data(self):
        self.run_mode();self.reset_interval()
        c=replace(self.c,markdown_authorized=True)
        with patch("qq_delivery.experiment.StaticImage.prepare",return_value=("https://example.invalid/SECRET_URL.jpg",False)),patch("qq_delivery.experiment.StaticImage.verify",new=AsyncMock(return_value={"jpeg_verified":True})):
            result=self.run_mode("B-url",1,config=c)
            self.assertEqual(result["status"],"acknowledged")
            self.assertIn("url",self.adapter.requests[-1].json)
            self.assertNotIn("file_data",self.adapter.requests[-1].json)
            self.reset_interval()
            result=self.run_mode("C",2,config=c)
        self.assertEqual(result["status"],"acknowledged")
        self.assertEqual(self.adapter.requests[-1].json["msg_type"],2)
        self.assertIn("![img#1080px #2436px]",self.adapter.requests[-1].json["markdown"]["content"])
        with State(self.c).locked() as s:
            result=export(self.root/"report",s)
        self.assertNotIn("SECRET",json.dumps(result))

    def test_zero_ttl_uses_bounded_private_lease_and_D_rejection_never_reuploads(self):
        self.run_mode();self.reset_interval()
        self.adapter.responses=[(200,dict(file_info="SECRET_FILE_INFO",ttl=0)),(200,dict(id="SECRET_MESSAGE_ID"))]
        self.run_mode("A-data",1)
        with State(self.c).locked() as s:
            self.assertLessEqual(s.data["media"]["expires_at"],time.time()+1800)
        self.reset_interval()
        self.adapter.responses=[(400,dict(code=304082,message="SECRET_EXPIRED"))]
        self.assertEqual(self.run_mode("D",2)["status"],"error")
        self.assertEqual(len(self.adapter.requests),4)
        with State(self.c).locked() as s:self.assertIsNone(s.data["media"])

    def test_parallel_worker_lock_and_pause_are_fail_closed(self):
        with State(self.c).locked() as s:
            with self.assertRaises(Blocked):
                with State(self.c).locked():pass
            s.data["paused"]=True;s.save()
        with self.assertRaises(Blocked):self.run_mode()
        self.assertFalse(self.adapter.requests)

    def test_observation_rejects_unsynced_measured_times_and_secret_fields(self):
        self.run_mode()
        with State(self.c).locked() as s:
            sample=s.data["rows"][0]["sample"]
            with self.assertRaises(Blocked):observe(s,sample,dict(openid="SECRET"))
            with self.assertRaises(Blocked):observe(s,sample,dict(device="android",received=True,render_ok=True,
                clock_synced=False,duplicates=0,image_start_ms=10,complete_ms=20,clock_uncertainty_ms=1))

    def test_active_denial_records_numeric_code_and_stops_B_variants(self):
        self.adapter.responses=[(403,dict(code=112233,message="SECRET_ERROR"))]
        result=self.run_mode()
        self.assertEqual(result["error"]["code"],112233)
        self.assertNotIn("SECRET",json.dumps(result))
        self.reset_interval()
        with self.assertRaises(Blocked):self.run_mode("B-url",1)
        self.assertEqual(len(self.adapter.requests),1)

    def test_401_does_not_trigger_installed_sdk_hidden_retry(self):
        self.adapter.responses=[(401,dict(code=40001,message="SECRET"))]
        self.run_mode()
        self.assertEqual(len(self.adapter.requests),1)
        self.assertEqual(self.bot.get_authorization_header.await_count,1)

    def test_unknown_timeout_blocks_all_modes_without_fallback(self):
        self.adapter.responses=[TimeoutError("SECRET")]
        result=self.run_mode()
        self.assertEqual(result["status"],"unknown")
        self.reset_interval()
        with self.assertRaises(Blocked):self.run_mode("A-data",1)
        self.assertEqual(len(self.adapter.requests),1)

    def test_cancellation_is_persisted_unknown(self):
        self.adapter.responses=[asyncio.CancelledError()]
        with self.assertRaises(asyncio.CancelledError):self.run_mode()
        with State(self.c).locked() as s:self.assertEqual(s.data["rows"][0]["status"],"unknown")

    def test_crash_pending_is_unknown_and_budget_not_refunded(self):
        with State(self.c).locked() as s:
            s.reserve("B-data",self.event().message_id,"sha")
        with State(self.c).locked() as s:
            self.assertEqual(s.data["rows"][0]["status"],"unknown")
            self.assertEqual(s.data["rounds"][self.c.round_id],1)
            with self.assertRaises(Blocked):s.reserve("A-data",self.event(1).message_id,"sha",now=time.time()+30)

    def test_crash_between_call_append_and_dispatch_can_still_export(self):
        with State(self.c).locked() as s:
            row=s.reserve("B-data",self.event().message_id,"sha")
            row["calls"].append({});s.save()
        with State(self.c).locked() as s:
            result=export(self.root/"report",s)
        self.assertEqual(result["samples"][0]["status"],"unknown")
        self.assertIsNone(result["summaries"][0]["api_success_rate"])

    def test_listener_uses_one_existing_auth_owner_and_consumes_event_only_once(self):
        from qq_delivery_probe import listen
        self.run_mode();self.reset_interval()
        c=replace(self.c,max_sends_per_round=2)
        with patch("qq_delivery_probe.journal_trigger",return_value=self.event(1)),patch("qq_delivery_probe.standalone_bot",return_value=self.bot) as factory:
            asyncio.run(listen(c,["A-data"],2,self.root/"report"))
        self.assertEqual(factory.call_count,1)
        self.assertEqual(len(self.adapter.requests),3)

    def test_static_failure_is_not_counted_as_QQ_API_failure(self):
        self.run_mode();self.reset_interval()
        c=replace(self.c,markdown_authorized=True)
        with patch("qq_delivery.experiment.StaticImage.prepare",side_effect=Blocked("static_precheck")):
            self.assertEqual(self.run_mode("C",1,config=c)["status"],"blocked_before_send")
        with State(self.c).locked() as s:result=export(self.root/"report",s)
        group=next(g for g in result["summaries"] if g["mode"]=="C")
        self.assertEqual(group["qq_api_attempted_samples"],0)
        self.assertIsNone(group["api_success_rate"])

    def test_budget_interval_and_unique_event_persist_across_restarts(self):
        self.run_mode()
        with self.assertRaises(Blocked):self.run_mode(n=1)
        self.reset_interval()
        with self.assertRaises(Blocked):self.run_mode()
        self.run_mode(n=1);self.reset_interval();self.run_mode(n=2);self.reset_interval()
        with self.assertRaises(Blocked):self.run_mode("A-data",3)
        self.assertEqual(len(self.adapter.requests),3)

    def test_A_then_D_reuses_only_scoped_unexpired_media(self):
        self.run_mode();self.reset_interval()
        a=self.run_mode("A-data",1)
        self.assertEqual(a["status"],"acknowledged")
        upload,send=self.adapter.requests[1:]
        self.assertFalse(upload.json["srv_send_msg"])
        self.assertEqual(send.json["msg_type"],7)
        self.assertEqual(send.json["msg_id"],self.event(1).message_id)
        self.assertEqual(send.json["msg_seq"],1)
        self.reset_interval()
        d=self.run_mode("D",2)
        self.assertEqual(d["status"],"acknowledged")
        self.assertEqual(len(self.adapter.requests),4)
        self.assertEqual(self.adapter.requests[-1].json["media"],dict(file_info="SECRET_FILE_INFO"))
        with self.assertRaises(Blocked):
            with State(replace(self.c,group_openid="other")).locked():pass

    def test_expired_D_blocks_without_upload_or_automatic_fallback(self):
        self.run_mode();self.reset_interval();self.run_mode("A-data",1);self.reset_interval()
        with State(self.c).locked() as s:s.data["media"]["expires_at"]=0;s.save()
        with self.assertRaises(Blocked):self.run_mode("D",2)
        self.assertEqual(len(self.adapter.requests),3)

    def test_missing_ttl_does_not_create_reusable_credential(self):
        self.run_mode();self.reset_interval()
        self.adapter.responses=[(200,dict(file_info="SECRET_FILE_INFO")),(200,dict(id="SECRET_MESSAGE_ID"))]
        self.run_mode("A-data",1)
        with State(self.c).locked() as s:self.assertIsNone(s.data["media"])

    def test_observation_required_before_performance_and_unknown_not_success(self):
        self.run_mode();self.reset_interval()
        with self.assertRaises(Blocked):self.run_mode(n=1,config=replace(self.c,phase="performance"))
        with State(self.c).locked() as s:
            r=s.data["rows"][0]
            observe(s,r["sample"],dict(device="android",received=True,render_ok=True,clock_synced=True,
                duplicates=0,image_start_ms=100,complete_ms=200,clock_uncertainty_ms=20,quota_before=4,quota_after=3))
            self.assertTrue(s.passed("B-data"))

    def test_qualitative_delivery_confirmation_does_not_invent_client_timing(self):
        self.run_mode()
        with State(self.c).locked() as s:
            observe(s,s.data["rows"][0]["sample"],dict(device="android",received=True,render_ok=True,
                clock_synced=False,duplicates=0))
            result=export(self.root/"report",s)
            self.assertTrue(s.passed("B-data"))
        self.assertEqual(result["summaries"][0]["client_received_samples"],1)
        self.assertIsNone(result["summaries"][0]["client_complete_by_device"]["android"]["p50_ms"])

    def test_excluded_calls_remain_auditable_without_changing_comparison_or_preflight(self):
        self.run_mode()
        with State(self.c).locked() as s:
            observe(s,s.data['rows'][0]['sample'],dict(device='android',received=True,render_ok=True,
                clock_synced=False,duplicates=0))
        self.reset_interval()
        self.run_mode(n=1)
        with State(self.c).locked() as s:
            s.data['rows'][-1]['comparison_eligible']=False
            s.save()
            self.assertTrue(s.passed('B-data'))
            result=export(self.root/'report',s)
        self.assertEqual(len(result['samples']),2)
        self.assertEqual(result['summaries'][0]['attempts'],1)
        self.assertEqual(result['comparison_scope']['excluded_samples'],1)

    def test_unconfirmed_duplicate_count_remains_unknown_and_does_not_pass_preflight(self):
        self.run_mode()
        with State(self.c).locked() as s:
            observe(s,s.data['rows'][0]['sample'],dict(device='android',received=True,render_ok=True,
                clock_synced=False,duplicates=None))
            self.assertFalse(s.passed('B-data'))
            result=export(self.root/'report',s)
        self.assertEqual(result['summaries'][0]['client_received_samples'],1)
        self.assertIsNone(result['summaries'][0]['observed_duplicates'])
        self.assertEqual(result['summaries'][0]['client_complete_by_device']['android']['n'],0)

    def test_quota_lower_bound_is_consumed_conservatively_without_fabricated_delta(self):
        self.run_mode()
        with State(self.c).locked() as s:
            observe(s,s.data['rows'][0]['sample'],dict(device='android',received=True,render_ok=True,
                clock_synced=False,duplicates=0))
            s.data['active_quota_attestation']=dict(remaining_lower_bound=2,b_rows_count=1,
                reported_at=time.time(),source='administrator_report')
            s.save()
        c=replace(self.c,phase='performance',active_performance_authorized=True)
        for n in (1,2):
            self.reset_interval()
            self.assertEqual(self.run_mode(n=n,config=c)['status'],'acknowledged')
        self.reset_interval()
        with self.assertRaisesRegex(Blocked,'active_performance_permission_and_quota_required'):
            self.run_mode(n=3,config=c)
        with State(self.c).locked() as s:
            self.assertEqual(s.remaining_active_budget(),0)
            result=export(self.root/'report',s)
        self.assertTrue(all(g['active_quota_consumed'] is None for g in result['summaries']))
        self.assertEqual(result['active_quota_attestation']['remaining_lower_bound'],2)
        self.assertEqual(len(self.adapter.requests),3)

    def test_stale_or_invalid_quota_attestations_do_not_enable_sends(self):
        self.run_mode()
        with State(self.c).locked() as s:
            for values in [dict(remaining_lower_bound=900,b_rows_count=1,reported_at=time.time()-3601),
                           dict(remaining_lower_bound=900,b_rows_count=2,reported_at=time.time()),
                           dict(remaining_lower_bound=True,b_rows_count=1,reported_at=time.time())]:
                s.data['active_quota_attestation']=values
                self.assertEqual(s.remaining_active_budget(),0)

    def test_excluded_errors_are_preserved_without_claiming_no_API_was_called(self):
        self.adapter.responses=[(403,dict(code=112233,message='SECRET'))]
        self.run_mode()
        with State(self.c).locked() as s:
            s.data['rows'][0]['comparison_eligible']=False
            result=export(self.root/'report',s)
            self.assertFalse(s.passed('B-data'))
        self.assertEqual(result['status'],'partial_observation')
        self.assertEqual(result['summaries'],[])
        errors=json.loads((self.root/'report/qq-delivery-errors.json').read_text())
        self.assertEqual(len(errors['errors']),1)
        self.assertEqual(errors['errors'][0]['error']['code'],112233)

    def test_instrumented_installed_httpx_session_preserves_builders_without_network(self):
        import httpx
        from nonebot.drivers.httpx import Session
        captured=[]
        async def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200,json=dict(file_info="SECRET_FILE_INFO",ttl=600,id="SECRET_ID"))
        class LocalSession(Session):
            async def setup(self):
                self._client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.adapter.driver=SimpleNamespace(get_session=lambda **kw:LocalSession(**kw))
        result=self.run_mode(config=replace(self.c,transport="traced_httpx"))
        self.assertEqual(result["status"],"acknowledged")
        self.assertEqual(len(captured),1)
        self.assertTrue(captured[0]["srv_send_msg"])
        with State(self.c).locked() as s:
            record=s.data["rows"][0]["calls"][0]
            self.assertIn("client_creation_ms",record["timings"])
            self.assertIn("request_build_ms",record["timings"])

    def test_public_report_redacts_all_credentials_and_has_no_fake_client_time(self):
        self.run_mode()
        with State(self.c).locked() as s:result=export(self.root/"report",s)
        text="".join(p.read_text() for p in (self.root/"report").iterdir())
        self.assertNotIn("SECRET",text)
        self.assertNotIn("file_info",json.dumps(result["samples"]))
        self.assertIsNone(result["summaries"][0]["client_complete_by_device"]["android"]["p50_ms"])
        self.assertIsNone(result["summaries"][0]["active_quota_consumed"])

    def test_trace_ignores_secret_info_and_does_not_fake_dns_or_pool_wait(self):
        async def scenario():
            trace=HttpTrace()
            await trace("connection.connect_tcp.started",dict(host="SECRET_URL"))
            await trace("connection.connect_tcp.complete",dict(return_value="SECRET_SOCKET"))
            return trace
        trace=asyncio.run(scenario())
        self.assertEqual(trace.connects,1)
        self.assertNotIn("SECRET",repr(trace.intervals))

    def test_native_installed_event_representation_is_parsed_and_spoof_rejected(self):
        from nonebot.adapters.qq.event import GroupMessageCreateEvent
        event=GroupMessageCreateEvent(id="SECRET_EVENT",group_id="SECRET_GID",group_openid=self.c.group_openid,
            content="开始测试",timestamp="2026-11-13T00:00:00Z",author=dict(id="SECRET_ID",member_openid="SECRET_ADMIN",bot=False,member_role="admin"))
        native=f"2026-11-13 09:00:00 SUCCESS nonebot | QQ {self.c.bot_id} | {event.get_log_string()}"
        row=json.dumps(dict(MESSAGE=native,__REALTIME_TIMESTAMP=str(int(time.time()*1e6))))
        with patch("qq_delivery.events.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout=row)):
            trigger=journal_trigger(self.c,"B-data",bootstrap=True)
            self.assertEqual(trigger.group_openid,self.c.group_openid)
        with patch("qq_delivery.events.subprocess.run",return_value=SimpleNamespace(returncode=0,stdout=row.replace('SUCCESS nonebot','SUCCESS taiko_bot'))):
            with self.assertRaises(Blocked):journal_trigger(self.c,"B-data",bootstrap=True)

    def test_static_cache_isolated_and_cleanup_only_generated_jpegs(self):
        root=self.root/"qq-delivery-probe"
        c=replace(self.c,static_root=str(root),static_base_url="https://example.invalid/synthetic",
                  external_access_verified=True,domain_whitelisted=True)
        with State(c).locked() as s,patch("qq_delivery.images.subprocess.run",return_value=SimpleNamespace(returncode=0)):
            url,cached=StaticImage(c).prepare(self.jpeg,s)
            self.assertFalse(cached)
            again,cached=StaticImage(c).prepare(self.jpeg,s)
            self.assertEqual(url,again);self.assertTrue(cached)
        file=next(root.glob('probe-*.jpg'))
        other=root/'private.jpg';other.write_bytes(b'untouched')
        self.assertEqual(cleanup_static(root,300,now=file.stat().st_mtime+301),1)
        self.assertTrue(other.exists())

    def test_explicit_final_cleanup_does_not_remove_non_probe_assets(self):
        root=self.root/"qq-delivery-probe";root.mkdir()
        (root/".synthetic-only").write_text("qq-delivery-probe-v1\n")
        (root/"probe-test.jpg").write_bytes(b"synthetic")
        (root/"keep.jpg").write_bytes(b"private")
        self.assertEqual(cleanup_static(root,300,all_generated=True),1)
        self.assertEqual((root/"keep.jpg").read_bytes(),b"private")
        with self.assertRaises(Blocked):cleanup_static(self.root,300,all_generated=True)

    def test_static_publish_blocked_without_cleanup_timer(self):
        c=replace(self.c,static_root=str(self.root/"qq-delivery-probe"),static_base_url="https://example.invalid/synthetic",external_access_verified=True,domain_whitelisted=True)
        with State(c).locked() as s,patch("qq_delivery.images.subprocess.run",return_value=SimpleNamespace(returncode=3)):
            with self.assertRaises(Blocked):StaticImage(c).prepare(self.jpeg,s)
        self.assertFalse(Path(c.static_root).exists())

    def test_QA_private_umask_does_not_make_synthetic_public_image_unreadable(self):
        c=replace(self.c,static_root=str(self.root/"qq-delivery-probe"),static_base_url="https://example.invalid/synthetic",external_access_verified=True,domain_whitelisted=True)
        previous=os.umask(0o077)
        try:
            with State(c).locked() as s,patch("qq_delivery.images.subprocess.run",return_value=SimpleNamespace(returncode=0)):
                StaticImage(c).prepare(self.jpeg,s)
            root=Path(c.static_root)
            self.assertEqual(root.stat().st_mode&0o777,0o755)
            self.assertEqual(next(root.glob('probe-*.jpg')).stat().st_mode&0o777,0o644)
            self.assertEqual((Path(c.private_dir)/'state.json').stat().st_mode&0o777,0o600)
        finally:os.umask(previous)

    def test_p95_is_descriptive_for_small_samples(self):
        self.assertTrue(stats([1,2,3])["p95_descriptive"])
        self.assertEqual(stats([1,2,3])["p50_ms"],2)
        self.assertIsNone(stats([])["p50_ms"])


if __name__=="__main__":
    unittest.main()
