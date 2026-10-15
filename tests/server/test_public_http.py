"""Both real handlers on bounded loopback listeners, byte-identical wire bodies."""
import contextlib
import http.client
import json
import sys
import threading
import types
from pathlib import Path
from unittest.mock import patch
import pytest
from taiko_bot.services import public_api as live
from taiko_bot.runtime.player.center import public_score_token as tokens

@contextlib.contextmanager
def server(module):
    with patch.object(module.SongDataHandler, "log_message", lambda *args: None):
        http = module.ThreadingHTTPServer(("127.0.0.1", 0), module.SongDataHandler)
        worker = threading.Thread(target=http.serve_forever, kwargs={"poll_interval":0.01})
        worker.start()
        try: yield http.server_port
        finally:
            http.shutdown(); http.server_close(); worker.join(2)
            assert not worker.is_alive()

def call(port, method, path, body=None, headers=None):
    connection=http.client.HTTPConnection("127.0.0.1",port,timeout=2)
    try:
        connection.request(method,path,body=body,headers=headers or {})
        reply=connection.getresponse();data=reply.read()
        return reply.status, {k:v for k,v in reply.getheaders() if k not in {"Date","Server"}}, data
    finally: connection.close()

def test_public_http_contract_and_config_bytes(tmp_path,monkeypatch):
    old=types.ModuleType("frozen_public_api");old.__file__=str(tmp_path/"server.py")
    with patch.dict(sys.modules,{"plugins.utils.public_score_token":tokens}):
        exec((Path(__file__).parent/"fixtures/public_api_legacy.py").read_text(),old.__dict__)
    songs=tmp_path/"songs.json";aliases=tmp_path/"alias.json";config=tmp_path/"config.json"
    songs.write_text('[{"id":1,"song_name":"合成"}]');aliases.write_text('[{"id":1,"aliases":["别名",2]}]')
    for module in (live,old):
        for key,value in [("SONG_DATA_PATH",songs),("ALIAS_DATA_PATH",aliases),("CONFIG_PATH",config)]:monkeypatch.setattr(module,key,value)
        monkeypatch.setattr(module,"fetch_latest_userdata_by_token",lambda value:{"status":"ok","data":{"profile":{"userid":"123"}}})
    cases=[("GET","/api/song_data",None,200),("GET","/missing",None,404),("HEAD","/api/song_data",None,405),
        ("OPTIONS","/api/public-score/by-token",None,204),("OPTIONS","/api/token",None,204),
        ("POST","/api/token",b"{",400),("POST","/api/token",b"[]",400),("POST","/api/token",b"{}",400),
        ("POST","/api/token",b'{"token":" synthetic "}',200),
        ("POST","/api/public-score/by-token",b'{}',400),("POST","/api/public-score/by-token",b'[]',400),
        ("POST","/api/public-score/by-token",b'\xff',400),("POST","/api/public-score/by-token",b'x'*16385,413),
        ("POST","/api/public-score/by-token",b'{"token":"synthetic"}',200)]
    with server(live) as new_port, server(old) as old_port:
        for method,path,body,status in cases:
            expected=call(old_port,method,path,body);actual=call(new_port,method,path,body)
            assert actual[0]==status
            assert actual==expected
        assert json.loads(config.read_text())=={"cookie":"synthetic"}
        assert config.read_bytes()==b'{\n    "cookie": "synthetic"\n}\n'
        aliases.write_text('invalid')
        assert call(new_port,"GET","/api/song_data")==call(old_port,"GET","/api/song_data")
        assert call(new_port,"GET","/api/song_data")[0]==500
        for module in (live,old):
            def denied(_):raise tokens.PublicScoreTokenError(401,"invalid_token","合成拒绝")
            monkeypatch.setattr(module,"fetch_latest_userdata_by_token",denied)
        assert call(new_port,"POST","/api/public-score/by-token",b'{"token":"synthetic"}')==call(old_port,"POST","/api/public-score/by-token",b'{"token":"synthetic"}')
