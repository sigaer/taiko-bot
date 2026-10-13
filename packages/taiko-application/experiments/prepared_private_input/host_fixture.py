"""Synthetic host only: no storage, production data, merge kernel or network."""
from copy import deepcopy
from .dto import AuthorizedTarget, Provenance, PreparedPrivateInput


class PreparationDenied(RuntimeError):
    pass


class HostProviderFixture:
    def __init__(self, scenario='normal'):
        self.scenario = scenario
        self.members = ('111',) if scenario == 'normal' else ('111', '222')
        self.profile = self.members[0]
        self.revision = 1
        self.allowed = True
        self.reads = 0

    def target(self):
        return AuthorizedTarget('onebot_v11:fixture', 'onebot_v11:fixture',
            '111' if self.scenario == 'normal' else 'u0_fixture',
            self.members, self.profile, f'auth-{self.revision}')

    def payload(self):
        # Already prepared synthetic u0 data, not a second merge implementation.
        score = 800000 if self.scenario == 'normal' else (980000 if '333' in self.members else 950000)
        return {'_meta': {'full': True, 'ts': '2025-01-01 00:00:00'},
                'profile': {'mydon_name': 'Player-'+self.profile}, 'dojo': {},
                'achievement': {}, 'songs': [{'song_no': 7, 'level': 4,
                    'high_score': score, 'stage_cnt': len(self.members)*2}]}

    def observe(self, expected=None):
        if not self.allowed:
            raise PreparationDenied('fixture permission denied')
        target = self.target()
        if expected is not None and expected != target:
            raise PreparationDenied('fixture target changed')
        return target

    def legacy_read(self, user_id):
        self.observe()
        if user_id != self.target().user_id:
            raise PreparationDenied('fixture target changed')
        self.reads += 1
        return deepcopy(self.payload())

    def prepare(self, expected=None):
        target = self.observe(expected)
        current = self.legacy_read(target.user_id)
        view = f'fixture-view-{self.revision}'
        history = None if self.scenario == 'missing-history' else ({'capturedAt': '2025-01-01 00:00:00', 'payload': deepcopy(current)},)
        return PreparedPrivateInput(target, current, history,
            Provenance('synthetic-normal' if self.scenario == 'normal' else 'synthetic-u0',
                view, view if history is not None else None, self.members, self.profile, 'fixture-rule-v1'))

    def change_members(self):
        self.members = ('111', '333')
        self.revision += 1

    def change_profile(self):
        self.profile = self.members[-1]
        self.revision += 1

    def validate_delivery(self, prepared):
        self.observe(prepared.authorized_target)
