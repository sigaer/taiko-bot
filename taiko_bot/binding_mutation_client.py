"""Bounded private binding writes; exact nonce retry, no local authority."""
import hashlib
import json
import re
import time
from uuid import uuid4

import httpx

from .settings import Settings, get_settings
from .viewer_client import ViewerClientError, _build_headers, _normalize_center_bind_payload

BODY_LIMIT = 256 * 1024
DEADLINE_SECONDS = 90


def command_request_id(event, principal, action):
    if event is not None:
        identity = getattr(event, 'message_id', None) or getattr(event, 'id', None)
        if isinstance(identity, (str, int)) and not isinstance(identity, bool):
            identity = str(identity)
            stamp = getattr(event, 'time', None)
            stamp = stamp if isinstance(stamp, (int, str)) and not isinstance(stamp, bool) else None
            if 0 < len(identity) <= 256 and (stamp is None or len(str(stamp)) <= 64):
                text = json.dumps(['bind-message-v1', principal, action, type(event).__module__, identity, stamp], separators=(',', ':'))
                return hashlib.sha256(text.encode()).hexdigest()[:32]
    return uuid4().hex


def _failure(status):
    messages = {400:'绑定请求无效。',401:'中心访问凭据已失效。',403:'没有修改该绑定的权限。',
                404:'当前未绑定该鼓众广场ID。',409:'绑定状态已变化，请重新查询。',429:'中心请求过于频繁，请稍后重试。'}
    return ViewerClientError(messages.get(status, '中心绑定服务暂不可用，请稍后重试。'), status_code=status)


def _request(action, body, *, settings, request_id):
    principal=body.get('identityKey')
    if not isinstance(principal,str) or not re.fullmatch(r'[0-9]{1,128}|onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128}',principal):
        raise _failure(400)
    nonce = request_id if request_id is not None else uuid4().hex
    if not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', nonce):
        raise _failure(400)
    body = {**body, 'requestId':nonce}
    return post_center_binding_operation(action, body, settings=settings, attempts=2)


def post_center_binding_operation(action, body, *, settings, attempts=1):
    if action not in {'remove', 'visibility', 'score-token'} or attempts not in (1, 2):
        raise _failure(400)
    headers = _build_headers(settings, require_developer_token=True)
    url = settings.viewer_base_url.rstrip('/')+'/api/taiko/proxy/bind/'+action
    end = time.monotonic()+DEADLINE_SECONDS
    for attempt in range(attempts):
        try:
            remaining = end-time.monotonic()
            if remaining <= 0:
                raise _failure(504)
            timeout = httpx.Timeout(min(10, remaining), connect=min(5, remaining))
            with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
                with client.stream('POST', url, headers=headers, json=body) as response:
                    if 300 <= response.status_code < 400:
                        raise _failure(502)
                    if response.status_code >= 400:
                        raise _failure(response.status_code)
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=16384):
                        if time.monotonic() >= end:
                            raise _failure(504)
                        if len(data)+len(chunk) > BODY_LIMIT:
                            raise _failure(502)
                        data.extend(chunk)
                    payload = json.loads(data)
                    if not isinstance(payload, dict) or payload.get('ok') is not True:
                        raise _failure(502)
                    return payload
        except ViewerClientError as error:
            if error.status_code != 503 or attempt == attempts-1:
                raise
        except Exception:
            if attempt == attempts-1:
                raise _failure(502) from None
    raise _failure(502)


def _result(payload, action, principal, target=None):
    records=payload.get('bindings')
    if (payload.get('identityKey')!=principal or type(payload.get('found')) is not bool
            or not isinstance(records,list) or len(records)>128 or payload['found']!=bool(records)):
        raise _failure(502)
    ids,slots=set(),set()
    selected=[]
    for row in records:
        if (not isinstance(row,dict) or not isinstance(row.get('taikoId'),str)
                or not re.fullmatch(r'[0-9]{1,25}',row['taikoId']) or type(row.get('slot')) is not int or not 0<row['slot']<1_000_000
                or type(row.get('visible')) is not int or row['visible'] not in (0,1)
                or type(row.get('isCurrent')) is not bool or row.get('source') not in {'wahlap','hiroba','manual'}
                or row['taikoId'] in ids or row['slot'] in slots):
            raise _failure(502)
        ids.add(row['taikoId']);slots.add(row['slot'])
        if row['isCurrent']:selected.append(row)
    if records and (len(selected)!=1 or payload.get('currentTaikoId')!=selected[0]['taikoId']
            or payload.get('taikoId')!=selected[0]['taikoId'] or payload.get('currentSource')!=selected[0]['source']):
        raise _failure(502)
    effect = payload.get('operation')
    if not isinstance(effect, dict) or effect.get('kind') != action:
        raise _failure(502)
    if action == 'remove':
        if (set(effect) != {'kind','removed','needsConfirmation','targetTaikoId'} or effect['targetTaikoId'] != target
                or type(effect['removed']) is not bool or type(effect['needsConfirmation']) is not bool
                or effect['removed'] == effect['needsConfirmation']):
            raise _failure(502)
    elif set(effect) != {'kind','matched'} or type(effect['matched']) is not int or not 0 <= effect['matched'] <= 128:
        raise _failure(502)
    try:
        binding=_normalize_center_bind_payload(payload)
    except Exception:
        raise _failure(502) from None
    return {'binding': binding, **effect}


def remove_center_bind(identity_key, taiko_id, *, force_last=False, request_id=None, settings:Settings|None=None):
    cfg = settings or get_settings()
    if not isinstance(taiko_id,str) or not re.fullmatch(r'[0-9]{1,25}',taiko_id) or type(force_last) is not bool:
        raise _failure(400)
    payload = _request('remove', {'identityKey':identity_key,'taikoId':taiko_id,'forceLast':force_last}, settings=cfg, request_id=request_id)
    return _result(payload, 'remove', identity_key, taiko_id)


def set_center_bind_visibility(identity_key, visible, *, request_id=None, settings:Settings|None=None):
    cfg = settings or get_settings()
    if type(visible) is not int or visible not in (0,1):
        raise _failure(400)
    payload = _request('visibility', {'identityKey':identity_key,'visible':visible}, settings=cfg, request_id=request_id)
    return _result(payload, 'visibility', identity_key)
