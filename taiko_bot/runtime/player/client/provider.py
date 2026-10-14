"""Remote tinfo preparation; the center remains the private-read authority."""
from dataclasses import asdict
from hashlib import sha256
import json
import time
from taiko_application.private_input import AuthorizedTarget, PreparedPrivateInput, Provenance
from taiko_bot.settings import get_settings
from taiko_bot.viewer_client import fetch_center_bind_info, ViewerClientError
from taiko_bot.userdata_provider import _read, _normalize_payload, _private_history, UserdataProviderError
from taiko_bot.merged_source_id import build_center_virtual_user_id
from ..authority import TinfoDenied, TinfoUnavailable, AuthorizedDelivery


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TinfoHostProvider:
    def __init__(self, *, settings=None):
        self.settings = settings or get_settings()
        self.deadline = time.monotonic() + 180

    def snapshot(self, actor, principal):
        if time.monotonic() >= self.deadline:
            raise TinfoUnavailable()
        try:
            info = fetch_center_bind_info(principal, self.settings)
        except ViewerClientError:
            raise TinfoDenied(404) from None
        if not info:
            raise TinfoDenied(404)
        if actor != principal and not info['visible']:
            raise TinfoDenied()
        bindings = [asdict(item) for item in info.get('bindings') or []]
        observation = digest({'info': {k:v for k,v in info.items() if k != 'bindings'}, 'bindings':bindings})
        virtual = int(info.get('currentSlot', 1)) == 0 and len(bindings) >= 2
        if virtual:
            members = tuple(item['taiko_id'] for item in bindings if item['source'] != 'manual')
            index = next((i for i,item in enumerate(bindings) if item['is_current']), 0)
            if not members:
                raise TinfoUnavailable()
            profile = members[max(0, min(index, len(members)-1))]
            identity = build_center_virtual_user_id(principal)
        else:
            identity = str(info['id'])
            members, profile = (identity,), identity
        return AuthorizedTarget(actor, principal, identity, members, profile, observation)

    def prepare(self, actor, principal, *, include_history=False):
        target = self.snapshot(actor, principal)
        self._initial = target
        for attempt in range(2):
            if self.snapshot(actor, principal) != target:
                raise TinfoDenied()
            payload, view = _read('current', target.user_id, force_refresh=bool(attempt),
                                  settings=self.settings, with_view=True, deadline=self.deadline)
            history = None
            if include_history:
                history_payload, history_view = _read('history', target.user_id, force_refresh=bool(attempt),
                    settings=self.settings, with_view=True, deadline=self.deadline)
                if history_view != view:
                    continue
                history = tuple(_private_history(history_payload))
            if self.snapshot(actor, principal) != target:
                raise TinfoDenied()
            observation = digest(view)
            return PreparedPrivateInput(target, _normalize_payload(payload), history,
                Provenance('remote-source-view', observation, observation if include_history else None,
                    None, target.members, target.profile_source))
        raise TinfoUnavailable()

    def verify(self, prepared):
        target = prepared.authorized_target
        if self.snapshot(target.actor, target.principal) != target:
            raise TinfoDenied()
        # Includes live grant checks on cache hits/304. Never return this data
        # to the renderer: the captured input remains the only rendering view.
        try:
            _read('current', target.user_id, force_refresh=False,
                  settings=self.settings, deadline=self.deadline)
        except UserdataProviderError:
            raise TinfoDenied() from None
        if self.snapshot(target.actor, target.principal) != target:
            raise TinfoDenied()

    def verify_initial(self):
        target = self._initial
        if self.snapshot(target.actor, target.principal) != target:
            raise TinfoDenied()

    def prepare_b30(self, actor, principal, command):
        from .b30_history import observed_time
        from taiko_application.private_input import thaw
        N,args,use_v2,_,_=command
        include_history=not use_v2 and not args
        private=self.prepare(actor,principal,include_history=include_history)
        self.b30_observed_at=observed_time()
        self.b30_inputs=dict(observed_at=self.b30_observed_at,history_snapshots=thaw(private.history) or (),daily_points=[])
        if include_history:
            from .b30_history import build_daily_rating_points
            self.b30_inputs['daily_points']=build_daily_rating_points(private.authorized_target.user_id,N,
                json_path=self.settings.root_dir/'songs/rating_structured_with_ids.json',history_snapshots=thaw(private.history) or ())
        return private
