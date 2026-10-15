"""Private frame validation rejects untrusted requests before SQL."""
import pytest
from taiko_bot.runtime.player.center.viewer_qq_migration import run_viewer_qq_migration
from taiko_bot.runtime.player.center.viewer_source_authority import SourceAuthorityError

def frame():return dict(operationId='a'*32,action='migrate',principal='qq_official:Sender_',qq='12345',code='b'*32,
    actor={'kind':'developer','userId':1,'credential':'c'*64,'tokenId':'1'},grant={'kind':'service','tuple':[None]*10,'sources':'*'})

@pytest.mark.parametrize('field,value',[('operationId','invalid'),('action','read'),('principal','12345'),('principal','qq_official:Sender_ '),
    ('grant',{}),('grant',{'kind':'service','tuple':[]}),('grant',{'kind':'owner','tuple':[None]*10}),('actor',None),
    ('actor',{'kind':'developer','userId':True,'credential':'c'*64,'tokenId':'1'})])
def test_invalid_private_frame_does_not_connect(field,value):
    request=frame();request[field]=value
    with pytest.raises(SourceAuthorityError) as error:
        run_viewer_qq_migration(request,connection_factory=lambda:pytest.fail('Invalid private frame opened SQL'))
    assert error.value.status==400

def test_authority_error_preserves_fixed_status_for_cli():
    from taiko_bot.runtime.player.center.bot_qq_migration import QqMigrationAuthorityError
    for status in [401,403]:
        error=QqMigrationAuthorityError(status)
        assert error.status==status and error.code in {'unauthorized','denied'}
        assert 'password' not in str(error)
