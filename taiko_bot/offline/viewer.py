"""Installed Viewer adapters. Authorization remains in the calling Web service.

Capture filesystem/publication inputs here and reuse the owner renderers. This
module deliberately imports no bot entrypoints and contains no drawing algorithm.
"""
import datetime
import json
import os
from pathlib import Path
from .paths import root
from .score_calculator import compute_all_from_userdata, compute_recommendations_for_user
from .dani_progress import SUPPORTED_DANI_VERSIONS, _parser_service
from taiko_store.reader import read_current_json, score_read_view
from taiko_store import PublicationError


def _userdata_root():
    return Path(os.environ.get('TAIKO_USERDATA_DIR') or root() / 'userdata')


def _current(user_id):
    return read_current_json(_userdata_root(), str(user_id))


def _load_grade_index(version):
    return _parser_service()._load_grade_index(version)


def render_my_don_image(user_id, **kwargs):
    from taiko_bot.runtime.player.center.draw_dress import render_my_don_image as render
    return render(user_id, **kwargs)


def render_update_changes_image(user_id, **kwargs):
    from taiko_bot.runtime.player.center.draw_dress import render_update_changes_image as render
    return render(user_id, **kwargs)


def render_tcloud_image(user_id, **kwargs):
    from taiko_bot.runtime.player.center.display_support.tcloud import render_tcloud_image as render
    with score_read_view(_userdata_root(), str(user_id)) as view:
        userdata = view.decoded()
        image = render_my_don_image(user_id, score_view=view)
        return render(userdata, my_don_img=image, **kwargs)


def _progress(name, user_id, *args, **kwargs):
    from taiko_bot.runtime.player.center.progress_support import render
    return getattr(render, name)(user_id, *args, userdata=_current(user_id), **kwargs)


def render_pass_progress_image_bytes(user_id, *args, **kwargs):
    return _progress('render_pass_progress_image_bytes', user_id, *args, **kwargs)


def render_progress_image_bytes(user_id, *args, **kwargs):
    return _progress('render_progress_image_bytes', user_id, *args, **kwargs)


def render_star_progress_image_bytes(user_id, *args, **kwargs):
    return _progress('render_star_progress_image_bytes', user_id, *args, **kwargs)


def render_progress_image_bytes_by_list(user_id, *args, **kwargs):
    return _progress('render_progress_image_bytes_by_list', user_id, *args, **kwargs)


def render_dani_progress_image_bytes(user_id, *args, **kwargs):
    from taiko_bot.runtime.player.center.progress_support.dani_progress import render_dani_progress_image_bytes as render
    with score_read_view(_userdata_root(), str(user_id)) as view:
        # Dani selects the latest matching dojo by the original filename. The
        # time-only B30 DTO drops that provenance and raises KeyError downstream.
        history = []
        for name in view.history_names():
            try:
                payload = view.decoded("history/" + name)
            except (OSError, UnicodeError):
                if view.manifest is not None:
                    raise PublicationError("Canonical history is unavailable") from None
                continue
            except ValueError:
                # Keep the existing exclusion of malformed historical JSON.
                continue
            history.append(dict(fileName=name, payload=payload))
        return render(user_id, *args, userdata=view.decoded(), history_snapshots=history, **kwargs)


def generate_dim_top_image(results, N, dim, user_id=None, **kwargs):
    from taiko_bot.runtime.player.center.b30_support.dimension import generate_dim_top_image as render
    return render(results, N, dim, user_id=user_id, userdata=_current(user_id) if user_id is not None else None, **kwargs)


def generate_top_N_image(results, N=20, user_id=None, **kwargs):
    from taiko_bot.runtime.player.center.b30_support.score_calculator import generate_top_N_image as render
    observed = None
    if user_id is not None:
        with score_read_view(_userdata_root(), str(user_id)) as view:
            observed = str(datetime.datetime.fromtimestamp(round(view.file_times('current')['ctime'])))
    return render(results, N, user_id=user_id, observed_at=observed, **kwargs)


def generate_recommend_image(recs, *, user_id=None, **kwargs):
    from taiko_bot.runtime.player.center.recommendation_support.score_calculator import generate_recommend_image as render
    return render(recs, user_id=user_id, userdata=_current(user_id) if user_id is not None else None, **kwargs)


def generate_rating_trend_image(user_id, N=20, json_path='./songs/rating_structured_with_ids.json', max_days=30, **kwargs):
    from taiko_bot.runtime.player.center.b30_history import _history_snapshot_inputs, _reconstruct_user_snapshots, _build_daily_rating_points_from_view
    from taiko_bot.runtime.player.center.trend_support.score_calculator import generate_rating_trend_image_with_status
    with score_read_view(_userdata_root(), str(user_id)) as view:
        snapshots = _reconstruct_user_snapshots(list(_history_snapshot_inputs(view)))
        points = _build_daily_rating_points_from_view(user_id, N, json_path, max_days, _publication_store=view.store, snapshots=snapshots)
        return generate_rating_trend_image_with_status(user_id, N, json_path, max_days, prepared_points=points, **kwargs)[1]


def render_b30_image(user_id, N=30, **kwargs):
    from taiko_bot.runtime.player.center.daily_ability import archive, SHANGHAI
    from taiko_bot.runtime.player.bxx_summary import comparison
    from taiko_bot.runtime.player.center.b30_support.b30_render import render_b30_image as render
    with score_read_view(_userdata_root(), str(user_id)) as view:
        current = view.decoded()
        prepared = {}
        try:
            with archive(user_id, 'v1-top20', userdata_dir=view.store.root,
                         publication_store=view.store, writable=False) as days:
                prepared = comparison(days, records=current.get('songs', []), count=N,
                    version='v1' if kwargs.get('collapse_duplicate_versions', False) else 'v1-unmerged',
                    captured=datetime.datetime.now(SHANGHAI).isoformat(),
                    source_ref=view.manifest['files']['current']['sha256'] if view.manifest else None)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError, PublicationError, OSError):
            pass
        observed = str(datetime.datetime.fromtimestamp(round(view.file_times('current')['ctime'])))
        return render(user_id, N, userdata=current, comparison=prepared, observed_at=observed, **kwargs)
