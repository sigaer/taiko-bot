from __future__ import annotations

from taiko_bot import domain as _domain
from functools import partial
from sakura_taiko_core.parser import hiroba as _hiroba

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

DIFFICULTY_BY_CLASS = _hiroba.DIFFICULTY_BY_CLASS

DEFAULT_HIROBA_SYNC_LEVELS = _hiroba.DEFAULT_HIROBA_SYNC_LEVELS

BADGE_NAME_TO_RANK = _hiroba.BADGE_NAME_TO_RANK


HirobaProfile = _hiroba.ClientHirobaProfile


HirobaSongRef = _hiroba.ClientHirobaSongRef


HirobaScoreDetail = _hiroba.HirobaScoreDetail


_parse_int = _hiroba._parse_int


_direct_div_text = _hiroba._direct_div_text


parse_profile = partial(_hiroba.parse_profile, profile=_hiroba.HIROBA_CLIENT_PROFILE)


parse_mypage_achievement = partial(_hiroba.parse_mypage_achievement, profile=_hiroba.HIROBA_CLIENT_PROFILE)


_level_from_link = _hiroba._level_from_link


_is_played_crown_src = _hiroba._is_played_crown_src


parse_score_list_page = partial(_hiroba.parse_score_list_page, profile=_hiroba.HIROBA_CLIENT_PROFILE)


merge_song_refs = partial(_hiroba.merge_song_refs, profile=_hiroba.HIROBA_CLIENT_PROFILE)


_badge_from_src = _hiroba._badge_from_src


_crown_from_src = partial(_hiroba._crown_from_src, profile=_hiroba.HIROBA_CLIENT_PROFILE)


parse_score_detail = partial(_hiroba.parse_score_detail, profile=_hiroba.HIROBA_CLIENT_PROFILE)


filter_song_refs_by_levels = partial(_hiroba.filter_song_refs_by_levels, profile=_hiroba.HIROBA_CLIENT_PROFILE)


enumerate_fetch_tasks = _hiroba.enumerate_fetch_tasks
