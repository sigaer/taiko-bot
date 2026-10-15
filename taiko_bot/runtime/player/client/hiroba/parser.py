from __future__ import annotations


from functools import partial

from sakura_taiko_core.parser import hiroba as _hiroba

parse_profile = partial(_hiroba.parse_profile, profile=_hiroba.HIROBA_CLIENT_PROFILE)
