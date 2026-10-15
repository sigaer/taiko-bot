from __future__ import annotations


import re

import threading

from .bot_binding_authority import normalize_bot_principal

from .bot_binding_mutation import _read, principal_lock_name

from .source_mutation import AuthorizedPublicationStore

_admission=threading.BoundedSemaphore(2)

class NativeWahlapDenied(ValueError):
    def __init__(self):super().__init__('请使用自己的当前国服实账号更新。')

class NativeWahlapUnavailable(RuntimeError):
    def __init__(self):super().__init__('更新暂不可用，请稍后重试。')

def update_native_wahlap(principal,identity,*,connection_factory,userdata_root,include_image=True,show_all=False,sync=None,render=None):
    if (not isinstance(principal,str) or principal!=principal.strip() or not isinstance(identity,str)
            or not re.fullmatch(r'[0-9]{1,25}',identity) or re.fullmatch(r'98[0-9]{16}',identity)
            or type(include_image) is not bool or type(show_all) is not bool):raise NativeWahlapDenied()
    try:principal=normalize_bot_principal(principal)
    except Exception:raise NativeWahlapDenied() from None
    if not _admission.acquire(timeout=30):raise NativeWahlapUnavailable()
    connection=cursor=None
    try:
        connection=connection_factory();cursor=connection.cursor()
        rows,virtual=_read(cursor,principal,locked=False)
        selected=next((row for row in rows if row.current),rows[0] if rows else None)
        if virtual or selected is None or selected.identity!=identity or selected.source!='wahlap':raise NativeWahlapDenied()
        expected=selected;connection.commit()
        store=AuthorizedPublicationStore(userdata_root,identity)
        with store.exclusive():
            cursor.execute('SELECT GET_LOCK(%s,5)',(principal_lock_name(principal),))
            if cursor.fetchone()!=(1,):raise NativeWahlapUnavailable()
            connection.begin()
            def prove():
                store._require_lock(write=True)
                actual,active_virtual=_read(cursor,principal)
                current=next((row for row in actual if row.current),actual[0] if actual else None)
                if active_virtual or current!=expected:raise NativeWahlapDenied()
            store.authorize=prove;prove()
            if sync is None:
                from .update_user import getUserData
                sync=getUserData
            result=sync(identity,publication_store=store)
            prove()
            if type(result) is not int or result not in (0,-1,404):raise NativeWahlapUnavailable()
            image=None
            if result==0 and include_image:
                try:
                    if render is None:
                        from .draw_dress import render_update_changes_image
                        render=render_update_changes_image
                    image=render(int(identity),show_all=show_all,score_view=store.reader())
                    if not isinstance(image,bytes) or not 0<len(image)<=16*1024**2:image=None
                except Exception:image=None  # Preserve existing text-only success.
            prove();connection.commit();store._require_lock(write=True)
            return {'ok':result==0,'message':{0:'更新成功！',-1:'更新失败，怎么回事呢？',404:'请确认绑定鼓众ID是否正确？'}[result],'image':image}
    except Exception as error:
        if connection is not None:
            try:connection.rollback()
            except Exception:pass
        if isinstance(error,NativeWahlapDenied):raise
        raise NativeWahlapUnavailable() from None
    finally:
        if cursor is not None:
            try:cursor.execute('SELECT RELEASE_LOCK(%s)',(principal_lock_name(principal),))
            except Exception:pass
            try:cursor.close()
            except Exception:pass
        if connection is not None:
            try:connection.close()
            except Exception:pass
        _admission.release()
