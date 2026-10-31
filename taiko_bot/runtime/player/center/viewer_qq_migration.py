"""Center principal capability proof around the shared native SQL transaction."""
import re
import json
from .bot_qq_migration import (
    issue_qq_migration_code,migrate_qq_bindings,QqMigrationDenied,QqMigrationAuthorityError,
)
from .viewer_source_authority import validate_source_actor,SourceAuthorityError,require_legacy_developer_grant


def _deny(status=403):raise QqMigrationAuthorityError(status)


def require_qq_migration_authority(cursor, actor, grant, principal, data):
    cursor.execute('SELECT id FROM web_user_accounts WHERE id=%s FOR UPDATE',(actor['userId'],))
    if cursor.fetchone()!=(actor['userId'],):_deny(401)
    if actor['kind']=='session':
        cursor.execute('SELECT user_id FROM web_user_sessions WHERE session_token=%s AND expires_at>NOW() FOR UPDATE',(actor['credential'],))
        if cursor.fetchone()!=(actor['userId'],):_deny(401)
    else:
        cursor.execute("SELECT CAST(id AS CHAR),user_id FROM web_developer_tokens WHERE token_hash=%s AND status='active' AND revoked_at IS NULL FOR UPDATE",(actor['credential'],))
        if cursor.fetchone()!=(actor['tokenId'],actor['userId']):_deny(401)
    if grant.get('kind')=='developer':
        try:require_legacy_developer_grant(cursor,actor,grant,lock=True)
        except SourceAuthorityError as error:_deny(error.status)
    elif grant.get('kind')=='owner':
        match=re.fullmatch(r'onebot_v11:([1-9][0-9]{4,14})',principal)
        if match is None:_deny()
        cursor.execute("""SELECT CAST(id AS CHAR),user_id,qq_number,status,DATE_FORMAT(verified_at,'%%Y-%%m-%%dT%%H:%%i:%%s')
            FROM web_user_qq_bindings WHERE user_id=%s AND qq_number=%s AND status='active' LIMIT 1 FOR UPDATE""",(actor['userId'],match[1]))
        row=cursor.fetchone()
        if row is None or list(row)!=grant.get('tuple') or not row[4] or grant.get('target') is not None:_deny()
    elif grant.get('kind')=='service' and actor['kind']=='developer':
        cursor.execute("""SELECT CAST(id AS CHAR),developer_user_id,service_name,scopes_json,sources_json,revision_nonce,status,
            DATE_FORMAT(expires_at,'%%Y-%%m-%%dT%%H:%%i:%%s'),issued_by_user_id,principals_json
            FROM taiko_source_service_grants WHERE developer_token_id=%s AND status='active'
            AND (expires_at IS NULL OR expires_at>NOW()) LIMIT 1 FOR UPDATE""",(actor['tokenId'],))
        row=cursor.fetchone()
        if (row is None or list(row)!=grant.get('tuple') or row[1]!=actor['userId']
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',row[2]) or not re.fullmatch(r'[a-f0-9]{32}',row[5])):_deny()
        scopes,sources,principals=[json.loads(row[i]) if isinstance(row[i],str) and len(row[i].encode())<=24576 else None for i in (3,4,9)]
        if not isinstance(scopes,list) or 'bind_migrate' not in scopes:_deny()
        if principals!='*' and (not isinstance(principals,list) or not 0<len(principals)<=128 or len(set(principals))!=len(principals)
                or any(not isinstance(v,str) or not re.fullmatch(r'[0-9]{1,128}|onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128}',v) for v in principals)
                or principal not in principals):_deny()
        if sources!='*':
            if (not isinstance(sources,list) or not 0<len(sources)<=128 or len(set(sources))!=len(sources)
                    or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',v) for v in sources)):_deny()
            if data and any(row.identity not in sources for rows,_ in data.values() for row in rows):_deny()
        if grant.get('sources')!=(sources if sources=='*' else sorted(sources)):_deny()
    else:_deny()


def _payload(principal,data,cursor):
    rows,virtual=data
    selected=next((row for row in rows if row.current),rows[0] if rows else None)
    bindings=[]
    for row in rows:
        display=row.identity
        if row.source=='manual':
            cursor.execute('SELECT nickname FROM taiko_manual_accounts WHERE taiko_id=%s LIMIT 1',(row.identity,))
            account=cursor.fetchone()
            if account is None or not isinstance(account[0],str) or not 0<len(account[0])<=64:_deny()
            display=account[0]
        bindings.append(dict(slot=row.slot,taikoId=row.identity,visible=row.visible,isCurrent=row==selected,source=row.source,
            displayName=display,isManual=row.source=='manual',canExternalSync=row.source!='manual'))
    result=dict(ok=True,found=bool(rows),identityKey=principal,bindings=bindings)
    if selected:
        current_virtual=virtual and sum(row.source!='manual' for row in rows)>=2
        result.update(taikoId=selected.identity,visible=selected.visible,currentTaikoId=selected.identity,
            currentSlot=0 if current_virtual else selected.slot,currentVirtual=current_virtual,currentSource=selected.source)
    return result


def run_viewer_qq_migration(request, *, connection_factory):
    if (not isinstance(request,dict) or not isinstance(request.get('operationId'),str) or not re.fullmatch(r'[a-f0-9]{32}',request['operationId'])
            or request.get('action') not in {'issue','migrate'} or not isinstance(request.get('principal'),str)
            or not re.fullmatch(r'onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128}',request['principal'])
            or not isinstance(request.get('grant'),dict) or request['grant'].get('kind') not in {'owner','service','developer'}
            or (request['grant']['kind']!='developer' and (not isinstance(request['grant'].get('tuple'),list) or len(request['grant']['tuple'])!=(5 if request['grant']['kind']=='owner' else 10)))):
        raise SourceAuthorityError(400,'invalid_request')
    actor=validate_source_actor(request.get('actor'));grant=request['grant'];principal=request['principal'];captured=[None]
    def authorize(cursor,data):
        require_qq_migration_authority(cursor,actor,grant,principal,data)
        if data and principal in data:captured[0]=_payload(principal,data[principal],cursor)
    if request['action']=='issue':
        code=issue_qq_migration_code(principal,connection_factory=connection_factory,authorize=authorize)
        result=dict(ok=True,identityKey=principal,qq=principal.split(':',1)[1],code=code,expiresInSeconds=600)
    else:
        mutation=migrate_qq_bindings(request.get('qq'),principal,code=request.get('code',''),connection_factory=connection_factory,authorize=authorize)
        result={**captured[0],'operation':dict(kind='qq-migrate',qq=request['qq'],sourceCurrentId=mutation.source_current_id,
            firstBinding=mutation.first_binding,replayed=mutation.replayed)}
    return dict(operationId=request['operationId'],payload=result)
