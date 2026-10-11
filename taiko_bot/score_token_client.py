"""Center-only minting; one request, no automatic token rotation retry."""
import re

from taiko_runtime.platform_adapter import format_identity_for_display
from .binding_mutation_client import post_center_binding_operation
from .settings import get_settings
from .viewer_client import ViewerClientError


def issue_center_score_token(taiko_id, identity_key, *, settings=None):
    if (not isinstance(taiko_id, str) or not re.fullmatch(r'[0-9]{1,25}', taiko_id)
            or re.fullmatch(r'98[0-9]{16}', taiko_id)
            or not isinstance(identity_key, str)
            or not re.fullmatch(r'onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128}', identity_key)):
        raise ViewerClientError('请使用自己的当前实账号生成成绩 token。', status_code=403)
    result = post_center_binding_operation('score-token', {'identityKey': identity_key, 'taikoId': taiko_id},
        settings=settings or get_settings(), attempts=1)
    token = result.get('token')
    if (result.get('identityKey') != identity_key or result.get('taikoId') != taiko_id
            or not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{48}', token)
            or result.get('tokenMask') != token[:8]+'...'+token[-8:]):
        raise ViewerClientError('中心成绩 token 返回无效，请稍后重试。', status_code=502)
    return {'taiko_id': taiko_id, 'owner_identity': identity_key,
        'owner_display': format_identity_for_display(identity_key), 'token': token, 'token_mask': result['tokenMask']}
