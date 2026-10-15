from __future__ import annotations


from dataclasses import dataclass

from taiko_bot.score_token_client import issue_center_score_token

from taiko_bot.viewer_client import ViewerClientError

@dataclass
class PublicScoreTokenError(Exception):
    status_code: int
    error: str
    message: str

    def __str__(self):
        return self.message

def issue_public_score_token_for_taiko_id(taiko_id, *, identity_key=None):
    try:
        return issue_center_score_token(taiko_id, identity_key)
    except ViewerClientError as error:
        raise PublicScoreTokenError(error.status_code, 'center_token_unavailable', str(error)) from None
    except Exception:
        raise PublicScoreTokenError(503, 'center_token_unavailable', '中心成绩 token 服务暂不可用，请稍后重试。') from None
