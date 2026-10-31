import unittest

from taiko_bot.runtime.player.center.viewer_source_authority import (
    require_legacy_developer_grant, SourceAuthorityError,
)


class Cursor:
    def __init__(self, application):
        self.application = application
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query, self.params = query, params

    def fetchone(self):
        return (self.application,) if self.application else None


class LegacyDeveloperAuthorityTests(unittest.TestCase):
    actor = dict(kind='developer', userId=21, tokenId='31', credential='a'*64)
    grant = dict(kind='developer', applicationId='41')

    def test_native_worker_rechecks_approval_and_active_credential_under_lock(self):
        cursor = Cursor('41')
        require_legacy_developer_grant(cursor, self.actor, self.grant, lock=True)
        self.assertEqual(cursor.params, ('31', 21, 'a'*64))
        for condition in ("app.status='approved'", "t.status='active'", 't.revoked_at IS NULL', 'a.email_verified=1', 'FOR UPDATE'):
            self.assertIn(condition, cursor.query)

    def test_revoked_approval_and_replaced_application_fail(self):
        for application in (None, '42'):
            with self.subTest(application=application), self.assertRaises(SourceAuthorityError):
                require_legacy_developer_grant(Cursor(application), self.actor, self.grant)

    def test_cookie_and_forged_policy_do_not_become_legacy_developer(self):
        for actor, grant in (({**self.actor, 'kind':'session'}, self.grant), (self.actor, {**self.grant, 'sources':'*'})):
            with self.assertRaises(SourceAuthorityError):
                require_legacy_developer_grant(Cursor('41'), actor, grant)


if __name__ == '__main__':
    unittest.main()
