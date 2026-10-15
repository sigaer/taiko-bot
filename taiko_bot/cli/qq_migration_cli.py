"""Private SQL-only local QQ migration task; secrets never enter argv/logs."""
import json
import logging
import signal
import sys
import types
from pathlib import Path
from contextlib import redirect_stdout
import pymysql
from taiko_bot.runtime.player.center.taiko_db import _db_config
from taiko_bot.runtime.player.center.viewer_qq_migration import run_viewer_qq_migration
from taiko_bot.runtime.player.center.bot_qq_migration import QqMigrationDenied
from taiko_bot.runtime.player.center.viewer_source_authority import SourceAuthorityError
class Discard:
    def write(self,text):return len(text)
    def flush(self):pass
def main():
    logging.disable(logging.CRITICAL);signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(45)
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise SourceAuthorityError(400,'invalid_request')
        try:request=json.loads(raw)
        except (ValueError,UnicodeError):raise SourceAuthorityError(400,'invalid_request') from None
        config=_db_config();factory=lambda:pymysql.connect(**config,connect_timeout=5,read_timeout=10,write_timeout=10)
        with redirect_stdout(Discard()):result=run_viewer_qq_migration(request,connection_factory=factory)
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False,separators=(',',':')))
    except (QqMigrationDenied,SourceAuthorityError) as error:
        print(json.dumps({'ok':False,'status':error.status,'error':error.code},separators=(',',':')))
    except Exception:print('{"ok":false,"status":503,"error":"qq_migration_unavailable"}')
    finally:signal.alarm(0)
if __name__=='__main__':main()
