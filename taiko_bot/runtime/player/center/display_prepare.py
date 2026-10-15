"""Host-only SQL and title preparation for captured personal displays."""
import logging
from taiko_application.private_input import thaw
from .display_settings import load_web_mydon_showcase_settings
from .display_host_support import custom_title, song_title_showcase


def prepare(provider, private):
    provider.display_options = {}
    if private.current_failure:
        return
    try:
        provider.verify(private)
        settings = load_web_mydon_showcase_settings(private.authorized_target.user_id,
                                                    connection_factory=provider._connection_factory)
        try:
            records = custom_title.list_custom_titles(connection_factory=provider._connection_factory)
        except Exception:
            logging.exception('failed_to_load_custom_titles_for_showcase')
            records = []
        songs = thaw(private.current).get('songs') or []
        if settings.title_overrides:
            titles = song_title_showcase.resolve_song_title_showcase_selection(
                songs, settings.title_overrides, custom_records=records, limit=5)
        else:
            titles = song_title_showcase.infer_song_title_showcase(songs, custom_records=records, limit=5)
        provider.display_options = dict(title_overrides=settings.title_overrides,
                                        showcase_layout=settings.showcase_layout,
                                        prepared_titles=tuple(titles))
    except Exception as error:
        from ..authority import TinfoDenied, TinfoUnavailable
        if isinstance(error,(TinfoDenied,TinfoUnavailable)):
            raise
        provider.display_error = error
    provider.verify(private)
