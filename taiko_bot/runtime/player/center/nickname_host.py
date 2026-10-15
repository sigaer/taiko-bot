"""Optional authenticated caller nickname for the otherwise public title query."""
from .. import entry
from taiko_application.private_input import thaw
from .song_title_query import extract_player_nickname

def prepare_nickname(event, matcher):
    actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
    provider=entry.create_provider()
    try:
        private=provider.prepare(actor,actor)
    except (entry.TinfoDenied, entry.TinfoUnavailable):
        return '鼓手', matcher
    nickname=extract_player_nickname(thaw(private.current) or {})
    return nickname,entry.AuthorizedDelivery(matcher,provider,private)
