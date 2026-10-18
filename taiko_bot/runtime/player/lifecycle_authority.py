"""Metadata-only lifecycle proof; reuse the existing full binding observations.

No score preparation or Writer capability is needed to authorize account commands.
The center's SQL transaction / remote service remains the mutation authority.
"""
import asyncio
from contextvars import ContextVar
from functools import wraps
from nonebot.adapters import Event as MessageEvent
from . import entry
from .authority import AuthorizedDelivery, TinfoDenied, TinfoUnavailable

_active = ContextVar('taiko_lifecycle_request', default=None)
_locks = {}  # Active requests only; removed after the final waiter exits.

class BindingGuard:
    def __init__(self, actor):
        self.actor = actor
        self.provider = entry.create_provider()
        self.expected = self.observe()

    def observe(self):
        try:
            if entry.profile() == 'center':
                # Each metadata proof has its own read deadline; synchronization may
                # outlive a score query without weakening the binding comparison.
                return entry.create_provider()._snapshot(self.actor, self.actor)[2]
            return self.provider.snapshot(self.actor, self.actor)
        except TinfoDenied as error:
            if error.status == 404:
                return None
            raise

    def verify_initial(self):
        if self.observe() != self.expected:
            raise TinfoDenied()

    def rebase(self):
        self.expected = self.observe()

    def delivery(self, matcher):
        return AuthorizedDelivery(matcher, self, None)

class ManualRequest:
    def __init__(self, actor, command, host, event=None):
        self.guard = BindingGuard(actor)
        self.actor, self.command, self.host = actor, command, host
        self.event = event

    def session(self):
        if self.command in ('manual_delete', 'manual_delete_confirm'):
            return self.host.MANUAL_DELETE_CONFIRM_SESSIONS.get(self.actor)
        if self.command in ('manual_score_delete', 'manual_score_delete_confirm'):
            return self.host.MANUAL_SCORE_DELETE_CONFIRM_SESSIONS.get(self.actor)

    def check_confirmation(self):
        session = self.session()
        if self.command.endswith('_confirm') and session and session.get('expires_at', 0) >= self.host.time.time():
            if session.get('principal') != self.actor or session.get('binding_observation') != self.guard.expected:
                raise TinfoDenied()

    async def call(self, api, actor, action, **payload):
        if actor != self.actor:
            raise TinfoDenied()
        self.guard.verify_initial()
        identity = payload.get('taikoId')
        if identity:
            selected = self.host._get_current_bind_entry(actor)
            if (not selected or identity not in self.host._get_bind_ids(selected)
                    or self.host._infer_bind_source(identity, selected.get('sources') or {}) != 'manual'):
                raise TinfoDenied()
            self.guard.verify_initial()
        if action == 'create':
            from taiko_bot.binding_mutation_client import command_request_id
            payload['requestId'] = command_request_id(self.event, actor, 'manual-create')
        result = await api(actor, action, **payload)
        if action in ('create', 'claim', 'detach', 'delete-account'):
            self.guard.rebase()
            if action in ('create', 'claim') and result.get('taikoId'):
                selected = self.host._get_current_bind_entry(actor)
                if result['taikoId'] not in self.host._get_bind_ids(selected):
                    raise TinfoDenied()
        self.guard.verify_initial()
        return result

    async def finish(self, helper, matcher, event, *args, **kwargs):
        session = self.session()
        if self.command in ('manual_delete', 'manual_score_delete') and session:
            session.update(principal=self.actor, binding_observation=self.guard.expected)
        return await helper(self.guard.delivery(matcher), event, *args, **kwargs)

def manual_boundary(command, host):
    def decorate(function):
        @wraps(function)
        async def invoke(*args, **kwargs):
            event = kwargs.get('event') or args[0]
            actor = host._normalize_identity_key(host.get_identity_key(event=event))
            lock, users = _locks.get(actor, (asyncio.Lock(), 0))
            _locks[actor] = (lock, users + 1)
            try:
                async with lock:
                    request = ManualRequest(actor, command, host, event)
                    request.check_confirmation()
                    token = _active.set(request)
                    try:
                        return await function(*args, **kwargs)
                    finally:
                        _active.reset(token)
            except (TinfoDenied, TinfoUnavailable):
                matcher = getattr(entry.manual_cluster, command)
                await host._finish_text_reply(matcher, event, '绑定状态已变化或权限不可用，请查询当前绑定后重试。')
            finally:
                current, users = _locks[actor]
                if users == 1:
                    del _locks[actor]
                else:
                    _locks[actor] = (current, users - 1)
        return invoke
    return decorate

async def manual_call(api, *args, **kwargs):
    return await _active.get().call(api, *args, **kwargs)

async def manual_finish(helper, *args, **kwargs):
    return await _active.get().finish(helper, *args, **kwargs)

from nonebot.adapters import Bot
import inspect

class LifecycleRequest:
    def __init__(self, actor, command, host):
        self.guard = BindingGuard(actor)
        self.actor, self.command, self.host = actor, command, host

    def verify_initial(self):
        self.guard.verify_initial()

    def confirmation(self):
        if self.command in ('bind_remove', 'bind_remove_confirm'):
            return self.host.BIND_DELETE_CONFIRM_SESSIONS.get(self.actor)
        if self.command in ('bind', 'bind_confirm'):
            return self.host.BIND_VERIFY_SESSIONS.get(self.actor)

    def check_confirmation(self):
        session = self.confirmation()
        if self.command.endswith('_confirm') and session and session.get('expires_at', 0) > self.host._now_ts():
            if session.get('principal') != self.actor or session.get('binding_observation') != self.guard.expected:
                raise TinfoDenied()

    def stamp_confirmation(self):
        session = self.confirmation()
        if self.command in ('bind_remove', 'bind') and session:
            session.update(principal=self.actor, binding_observation=self.guard.expected)


def lifecycle_boundary(command, host):
    def decorate(function):
        @wraps(function)
        async def invoke(*args, **kwargs):
            event = kwargs.get('event') or args[0]
            actor = host._normalize_identity_key(host.get_identity_key(event=event))
            token = None
            try:
                if command == 'game_login_qr':
                    if not host._can_request_game_login_qr(event):
                        return await function(*args, **kwargs)
                    class QrGuard:
                        def verify_initial(self):
                            if not host._can_request_game_login_qr(event):
                                raise TinfoDenied()
                        def delivery(self, matcher):
                            return AuthorizedDelivery(matcher, self, None)
                    request = type('QrRequest', (), {'guard': QrGuard()})()
                else:
                    request = LifecycleRequest(actor, command, host)
                    request.check_confirmation()
                    if command == 'hiroba_update':
                        requested, _ = host._resolve_requested_identity_key(event)
                        if requested != actor:
                            raise TinfoDenied()
                token = _active.set(request)
                return await function(*args, **kwargs)
            except (TinfoDenied, TinfoUnavailable):
                if token is not None:
                    _active.reset(token)
                    token = None
                owner = entry.identity_cluster if hasattr(entry.identity_cluster, command) else entry.update_cluster
                await host._finish_text_reply(getattr(owner, command), event, '绑定状态已变化或权限不可用，请查询当前绑定后重试。')
            finally:
                if token is not None:
                    _active.reset(token)
        return invoke
    return decorate


def delivery_for(matcher):
    request = _active.get()
    if request is None or isinstance(matcher, AuthorizedDelivery):
        return matcher
    if isinstance(request, LifecycleRequest):
        request.stamp_confirmation()
    return request.guard.delivery(matcher)


def binding_mutation(function):
    """The existing SQL/API transaction performs the change; refresh its reply proof."""
    def before():
        request = _active.get()
        if request is not None:
            request.guard.verify_initial()
        return request
    if inspect.iscoroutinefunction(function):
        @wraps(function)
        async def invoke(*args, **kwargs):
            request = before()
            result = await function(*args, **kwargs)
            if request is not None:
                request.guard.rebase()
            return result
    else:
        @wraps(function)
        def invoke(*args, **kwargs):
            request = before()
            result = function(*args, **kwargs)
            if request is not None:
                request.guard.rebase()
            return result
    return invoke

def verify_active_binding():
    request = _active.get()
    if request is not None:
        request.guard.verify_initial()
