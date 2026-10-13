import copy
import dataclasses
from pathlib import Path
from types import SimpleNamespace
import pytest
from .dto import PreparedPrivateInput, AuthorizedTarget
from .host_fixture import HostProviderFixture, PreparationDenied
from .application_adapter import execute_prepared_score
from .oracle import run_legacy, canonical, error_result

SCENARIOS=['normal','u0','missing-history','changed-members','changed-profile']
QUERIES=['tinfo Neon','tinfo none','tinfo many','tinfo fuzzy','tinfo accepted','tinfo invalid-id','tinfo absent-record','bad','tinfo query-error']
RECORDS=[]


def host_for(scenario):
    host=HostProviderFixture(scenario)
    if scenario=='changed-members': host.change_members()
    if scenario=='changed-profile': host.change_profile()
    return host


def actual(prepared,text,failure=None):
    try:
        return canonical(execute_prepared_score(prepared,text,failure=failure))
    except Exception as e:
        return error_result(e)

@pytest.mark.parametrize('scenario',SCENARIOS)
@pytest.mark.parametrize('text',QUERIES)
def test_output_parity(scenario,text):
    host=host_for(scenario)
    old=run_legacy(host,text)
    prepared=host.prepare()
    before=host.reads
    new=actual(prepared,text)
    assert new==old
    assert host.reads==before
    if text=='tinfo query-error':
        assert old['raised']=='TypeError'
    else:
        assert 'raised' not in old
    RECORDS.append({'scenario':scenario,'text':text,'output':new})

@pytest.mark.parametrize('scenario',SCENARIOS)
@pytest.mark.parametrize('failure',['missing','error','type','jpeg'])
def test_error_parity(scenario,failure):
    host=host_for(scenario)
    old=run_legacy(host,'tinfo Neon',failure)
    new=actual(host.prepare(),'tinfo Neon',failure)
    assert old==new
    if failure=='jpeg':
        assert new['raised']=='UnidentifiedImageError'
    else:
        assert new['kind']=='text' and new['text']
    RECORDS.append({'scenario':scenario,'failure':failure,'output':new})

@pytest.mark.parametrize('change',['change_members','change_profile'])
def test_stale_target_is_rejected_then_reprepared(change):
    host=HostProviderFixture('u0')
    prepared=host.prepare()
    old_image=actual(prepared,'tinfo Neon')
    getattr(host,change)()
    with pytest.raises(PreparationDenied,match='target changed'):
        host.prepare(expected=prepared.authorized_target)
    with pytest.raises(PreparationDenied,match='target changed'):
        host.validate_delivery(prepared)
    fresh=host.prepare()
    host.validate_delivery(fresh)
    new_image=actual(fresh,'tinfo Neon')
    assert new_image==run_legacy(host,'tinfo Neon')
    assert new_image['sha256']!=old_image['sha256']
    assert fresh.provenance.current_view!=prepared.provenance.current_view
    assert fresh.authorized_target.user_id==prepared.authorized_target.user_id
    assert actual(prepared,'tinfo Neon')==old_image  # immutable snapshot, not permission to send


def test_missing_history_is_optional_for_tinfo():
    without=HostProviderFixture('missing-history').prepare()
    assert without.history is None
    assert actual(without,'tinfo Neon')==actual(HostProviderFixture('u0').prepare(),'tinfo Neon')


def test_revocation_blocks_prepare_and_delivery():
    host=HostProviderFixture()
    prepared=host.prepare()
    host.allowed=False
    before=host.reads
    for call in [host.prepare, lambda:host.validate_delivery(prepared)]:
        with pytest.raises(PreparationDenied,match='permission denied'): call()
    assert host.reads==before
    assert run_legacy(host,'tinfo Neon')=={'kind':'text','text':'fixture permission denied','delivery':'reply'}


def test_deep_immutability_and_ownership():
    host=HostProviderFixture('u0')
    raw=host.payload()
    prepared=dataclasses.replace(host.prepare(),current=raw)
    raw['profile']['mydon_name']='mutated'
    raw['songs'][0]['high_score']=0
    assert prepared.current['profile']['mydon_name']!='mutated'
    assert prepared.current['songs'][0]['high_score']==950000
    with pytest.raises(TypeError): prepared.current['profile']['mydon_name']='mutated'
    with pytest.raises(TypeError): prepared.history[0]['payload']['songs'][0]['high_score']=0
    with pytest.raises(dataclasses.FrozenInstanceError): prepared.current={}

@pytest.mark.parametrize('bad',[Path('/not-opened'),lambda:None,SimpleNamespace(store='handle'),object(),b'opaque'])
def test_capabilities_rejected_at_any_depth(bad):
    with pytest.raises(TypeError,match='JSON data only'):
        dataclasses.replace(HostProviderFixture().prepare(),current={'profile':{'nested':[bad]}})


def test_dto_fields_are_data_only():
    assert [f.name for f in dataclasses.fields(PreparedPrivateInput)]==['authorized_target','current','history','provenance']
    with pytest.raises(TypeError):
        PreparedPrivateInput(**{**{f.name:getattr(HostProviderFixture().prepare(),f.name) for f in dataclasses.fields(PreparedPrivateInput)},'writer':object()})
    with pytest.raises(ValueError):
        dataclasses.replace(HostProviderFixture().prepare().authorized_target,user_id='/private/path')

@pytest.mark.parametrize('field,value',[('members',('222','111')),('profile_source','222'),('history_view','other-view')])
def test_provenance_mismatch_rejected(field,value):
    prepared=HostProviderFixture('u0').prepare()
    with pytest.raises(ValueError):
        dataclasses.replace(prepared,provenance=dataclasses.replace(prepared.provenance,**{field:value}))

@pytest.mark.parametrize('change',['order','profile'])
def test_same_id_and_same_authorization_label_cannot_hide_composition_change(change):
    host=HostProviderFixture('u0')
    prepared=host.prepare()
    if change=='order': host.members=tuple(reversed(host.members))
    else: host.profile='222'
    # Do not bump the fixture observation label: the actual vector/profile must be checked.
    assert host.target().user_id==prepared.authorized_target.user_id
    assert host.target().authorization_observation==prepared.authorized_target.authorization_observation
    with pytest.raises(PreparationDenied,match='target changed'):
        host.validate_delivery(prepared)


def test_prepared_execution_cannot_reenter_the_host(monkeypatch):
    host=HostProviderFixture('u0')
    prepared=host.prepare()
    def forbidden(*a,**kw):
        pytest.fail('Application reentered the Host Provider')
    for name in ('prepare','legacy_read','observe','payload'):
        monkeypatch.setattr(host,name,forbidden)
    assert actual(prepared,'tinfo Neon')['kind']=='image'
