"""Granted Hiroba Source using real parsers/cooldown/sync/publication, fake HTTP client."""
import json
import pytest
from taiko_store import PublicationStore
from taiko_bot.runtime.player.center.hiroba import sync, cooldown, credentials
from taiko_bot.runtime.player.center import userdata_storage, daily_ability
from test_source_service import SQL, request, run, IDENTITY, BINDING
from test_hiroba_profile_and_stats import MYPAGE_HTML, SCORE_DETAIL_HTML
from test_hiroba_parser_crowns import SCORE_LIST_HTML

@pytest.fixture
def hiroba(tmp_path,monkeypatch):
    class Client:
        fail=False; logins=0; genres=[]
        def __init__(self,token=None,timeout=30):self.token=token or "synthetic";self.timeout=timeout
        def login(self,email,password,*,taiko_no):
            assert (email,password,taiko_no)==("synthetic@example.test","synthetic",IDENTITY)
            type(self).logins+=1
        def update_score(self):pass
        def fetch_mypage(self):return MYPAGE_HTML.replace("519635636897",IDENTITY)
        def fetch_score_list(self,genre):
            type(self).genres.append(genre)
            if self.fail:raise RuntimeError("synthetic remote failure")
            return SCORE_LIST_HTML if genre==1 else "<html></html>"
        def fetch_score_detail(self,song_no,level,**kwargs):return SCORE_DETAIL_HTML
    monkeypatch.setattr(sync,"HirobaClient",Client)
    monkeypatch.setattr(cooldown,"HIROBA_SYNC_COOLDOWN_PATH",tmp_path/"cooldown.json")
    monkeypatch.setattr(credentials,"HIROBA_TOKEN_DIR",tmp_path/"tokens")
    monkeypatch.setattr(userdata_storage,"_load_locked_song_keys",lambda _:set())
    monkeypatch.setattr(daily_ability,"capture_snapshot",lambda *a,**kw:None)
    fixture=(tmp_path/"userdata",tmp_path/"cache",{})
    db=SQL();db.binding=("11",IDENTITY,"hiroba",None)
    req=request(scope="hiroba_sync",email="synthetic@example.test",password="synthetic",grant={"kind":"owner","binding":BINDING|{"source":"hiroba"}})
    return Client,fixture,db,req

def test_private_hiroba_parser_writer_incremental_and_cooldown(hiroba):
    client,fixture,db,req=hiroba
    first=run(req,db,fixture)
    assert first["sequence"]==1 and client.genres==list(range(1,9))
    with PublicationStore(fixture[0],IDENTITY).shared() as store:
        data=json.loads(store.reader().current_raw())
        assert data["profile"]["userid"]==IDENTITY and data["_meta"]["source"]=="hiroba"
        assert data["songs"] and any(song["high_score"]>0 for song in data["songs"])
    with pytest.raises(sync.HirobaError):run(req,db,fixture)
    assert client.logins==1
    cooldown.release_hiroba_sync_slot(IDENTITY)
    assert run(req,db,fixture)["sequence"]==2
    with PublicationStore(fixture[0],IDENTITY).shared() as store:
        rows=[json.loads(store.reader().history_raw(name)) for name in store.reader().history_names()]
        assert len(rows)==2 and sum(bool(row["_meta"]["full"]) for row in rows)==1

def test_failed_hiroba_fetch_releases_slot_and_allows_recovery(hiroba):
    client,fixture,db,req=hiroba;client.fail=True
    with pytest.raises(RuntimeError):run(req,db,fixture)
    assert cooldown.peek_hiroba_sync_cooldown(IDENTITY) is None
    assert "rollback" in db.trace and db.trace[-1]=="close"
    client.fail=False
    assert run(req,db,fixture)["sequence"]==1
