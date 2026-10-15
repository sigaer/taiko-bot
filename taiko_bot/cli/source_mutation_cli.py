"""Private bounded local Source acquisition. No credentials in process argv."""
import json
import logging
import os
import signal
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path
import pymysql
from taiko_bot.runtime.player.center.taiko_db import _db_config
from taiko_bot.runtime.player.center.source_mutation import run_source_mutation
from taiko_bot.runtime.player.center.viewer_source_authority import SourceAuthorityError
class Discard:
    def write(self,text): return len(text)
    def flush(self): pass
def main():
    signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(180)
    logging.disable(logging.CRITICAL)
    try:
        raw=sys.stdin.buffer.read(32769)
        if len(raw)>32768: raise SourceAuthorityError(400,"invalid_request")
        try: request=json.loads(raw)
        except (ValueError,UnicodeError): raise SourceAuthorityError(400,"invalid_request") from None
        if isinstance(request,dict) and request.get("scope")=="hiroba_sync":signal.alarm(900)
        config=_db_config()
        factory=lambda:pymysql.connect(**config,connect_timeout=5,read_timeout=45,write_timeout=45)
        with redirect_stdout(Discard()):
            result=run_source_mutation(request,connection_factory=factory,userdata_root=os.environ["TAIKO_USERDATA_DIR"],cache_root=os.environ["TAIKO_ACCOUNT_CACHE_DIR"])
        print(json.dumps({"ok":True,"result":result},ensure_ascii=False,separators=(",",":")))
    except SourceAuthorityError as error:
        print(json.dumps({"ok":False,"status":error.status,"error":error.code},separators=(",",":")))
    except Exception as error:
        from taiko_bot.services.sync_dispatch_server import RequestError
        if isinstance(error,RequestError) and error.code in {"wahlap_user_not_found","wahlap_sync_failed"}:
            print(json.dumps({"ok":False,"status":error.status,"error":error.code}))
        else:
            print('{"ok":false,"status":503,"error":"source_unavailable"}')
    finally:signal.alarm(0)
if __name__=="__main__":main()
