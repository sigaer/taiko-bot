"""Private center QQ migration; no SQLite/JSON binding authority."""
import re
from .binding_mutation_client import post_center_binding_operation,binding_from_payload
from .settings import get_settings
from .viewer_client import ViewerClientError

def _failure(status):
    messages={400:'请按“绑定QQ QQ号 验证码”输入。',401:'中心访问凭据已失效。',
        403:'没有迁移该绑定的权限，请核对中心授权或重新申请验证码。',404:'未找到该 QQ 的历史绑定。',
        409:'迁移状态已变化，请查询当前绑定或重新申请验证码。',429:'请求过于频繁，请稍后重试。'}
    return ViewerClientError(messages.get(status,'QQ 迁移结果暂无法确认，请查询当前绑定后再重试。'),status_code=status)

def _principal(value):
    if not isinstance(value,str) or not re.fullmatch(r'onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128}',value):raise _failure(400)
    return value

def issue_center_qq_migration_code(principal, *, settings=None):
    principal=_principal(principal)
    match=re.fullmatch(r'onebot_v11:([1-9][0-9]{4,14})',principal)
    if match is None:raise _failure(403)
    result=post_center_binding_operation('qq-code',{'identityKey':principal},settings=settings or get_settings(),attempts=1,error_for_status=_failure)
    if (result.get('identityKey')!=principal or result.get('qq')!=match[1] or not isinstance(result.get('code'),str)
            or not re.fullmatch(r'[a-f0-9]{32}',result['code']) or type(result.get('expiresInSeconds')) is not int or result['expiresInSeconds']!=600):raise _failure(502)
    return result['code']

def migrate_center_qq_bindings(qq, principal, *, code='', settings=None):
    principal=_principal(principal)
    if (not isinstance(qq,str) or not re.fullmatch(r'[1-9][0-9]{4,14}',qq) or not isinstance(code,str)
            or (code and not re.fullmatch(r'[a-f0-9]{32}',code))):raise _failure(400)
    if principal!='onebot_v11:'+qq and not code:
        raise ViewerClientError('请用原 QQ 私聊旧 bot 发送“迁移验证码”，再发送“绑定QQ QQ号 验证码”。',status_code=403)
    result=post_center_binding_operation('qq-migrate',{'identityKey':principal,'qq':qq,'code':code},settings=settings or get_settings(),
        attempts=2 if code and principal!='onebot_v11:'+qq else 1,error_for_status=_failure)
    operation=result.get('operation')
    if (not isinstance(operation,dict) or set(operation)!={'kind','qq','sourceCurrentId','firstBinding','replayed'}
            or operation['kind']!='qq-migrate' or operation['qq']!=qq or type(operation['firstBinding']) is not bool
            or type(operation['replayed']) is not bool or not isinstance(operation['sourceCurrentId'],str)
            or not re.fullmatch(r'[0-9]{1,25}',operation['sourceCurrentId'])):raise _failure(502)
    return {'binding':binding_from_payload(result,principal),**operation}
