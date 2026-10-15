from __future__ import annotations


from datetime import datetime

from sakura_taiko_core.parser import hiroba_score as domain_score

def build_userdata(profile, details, achievement=None):
    return domain_score.build_userdata(profile, details, achievement, captured_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
